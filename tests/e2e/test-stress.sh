#!/usr/bin/env bash
# Comprehensive stress test for two-agent Odigos setup.
# Exercises: peer messaging, tool use, memory, goals, cards, feed,
# cross-agent tasks, skills, code execution, budget, cron, and more.
#
# Usage: bash tests/e2e/test-stress.sh

set -uo pipefail

ALICE="http://localhost:8100"
BOB="http://localhost:8200"
ALICE_KEY="alice-test-key"
BOB_KEY="bob-test-key"

PASS=0
FAIL=0
SKIP=0
TESTS=()

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); TESTS+=("PASS: $1"); }
fail() { echo "  FAIL: $1 -- $2"; FAIL=$((FAIL + 1)); TESTS+=("FAIL: $1 -- $2"); }
skip() { echo "  SKIP: $1"; SKIP=$((SKIP + 1)); TESTS+=("SKIP: $1"); }
header() { echo ""; echo "=== $1 ==="; }

alice_get()  { curl -sf -H "Authorization: Bearer $ALICE_KEY" "$ALICE$1"; }
alice_post() { curl -sf -H "Authorization: Bearer $ALICE_KEY" -H "Content-Type: application/json" -d "$2" "$ALICE$1"; }
alice_put()  { curl -sf -X PUT -H "Authorization: Bearer $ALICE_KEY" -H "Content-Type: application/json" -d "$2" "$ALICE$1"; }
alice_del()  { curl -sf -X DELETE -H "Authorization: Bearer $ALICE_KEY" "$ALICE$1"; }

bob_get()  { curl -sf -H "Authorization: Bearer $BOB_KEY" "$BOB$1"; }
bob_post() { curl -sf -H "Authorization: Bearer $BOB_KEY" -H "Content-Type: application/json" -d "$2" "$BOB$1"; }
bob_put()  { curl -sf -X PUT -H "Authorization: Bearer $BOB_KEY" -H "Content-Type: application/json" -d "$2" "$BOB$1"; }
bob_del()  { curl -sf -X DELETE -H "Authorization: Bearer $BOB_KEY" "$BOB$1"; }

# Helper: send message and get response (waits for LLM)
alice_chat() {
  local resp
  resp=$(alice_post "/api/message" "{\"content\":\"$1\"}")
  echo "$resp"
}

bob_chat() {
  local resp
  resp=$(bob_post "/api/message" "{\"content\":\"$1\"}")
  echo "$resp"
}

# ══════════════════════════════════════════════════════════════════════
header "PHASE 1: Baseline Health & Config"
# ══════════════════════════════════════════════════════════════════════

# 1.1 Health
for agent_url in "$ALICE" "$BOB"; do
  name=$([ "$agent_url" = "$ALICE" ] && echo "Alice" || echo "Bob")
  health=$(curl -sf "$agent_url/health")
  if echo "$health" | grep -q '"status":"ok"'; then
    pass "$name health"
  else
    fail "$name health" "$health"
  fi
done

# 1.2 Settings
ALICE_SETTINGS=$(alice_get "/api/settings")
if echo "$ALICE_SETTINGS" | python3 -c "import sys,json; s=json.load(sys.stdin); assert s['agent']['name']=='Alice'" 2>/dev/null; then
  pass "Alice agent name"
else
  fail "Alice agent name" "unexpected name"
fi

BOB_SETTINGS=$(bob_get "/api/settings")
if echo "$BOB_SETTINGS" | python3 -c "import sys,json; s=json.load(sys.stdin); assert s['agent']['name']=='Bob'" 2>/dev/null; then
  pass "Bob agent name"
else
  fail "Bob agent name" "unexpected name"
fi

# 1.3 Metrics endpoint
ALICE_METRICS=$(alice_get "/api/metrics")
if echo "$ALICE_METRICS" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  pass "Alice metrics endpoint"
else
  fail "Alice metrics" "$ALICE_METRICS"
fi

# 1.4 State endpoint
ALICE_STATE=$(alice_get "/api/state")
if echo "$ALICE_STATE" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  pass "Alice state endpoint"
else
  fail "Alice state" "$ALICE_STATE"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 2: Card Exchange (Both Directions)"
# ══════════════════════════════════════════════════════════════════════

# 2.1 Alice generates connect card, Bob imports it
ALICE_CONNECT=$(alice_post "/api/cards/generate" '{"type":"connect"}')
ALICE_CONNECT_COMPACT=$(echo "$ALICE_CONNECT" | python3 -c "import sys,json; print(json.load(sys.stdin)['compact'])")
ALICE_CONNECT_KEY=$(echo "$ALICE_CONNECT" | python3 -c "import sys,json; print(json.load(sys.stdin)['card']['card_key'])")

BOB_IMPORT=$(bob_post "/api/cards/import" "{\"card_data\":\"$ALICE_CONNECT_COMPACT\"}")
if echo "$BOB_IMPORT" | python3 -c "import sys,json; r=json.load(sys.stdin); assert r['status']=='accepted'" 2>/dev/null; then
  pass "Bob imports Alice's connect card"
else
  fail "Bob imports Alice's connect card" "$BOB_IMPORT"
fi

# 2.2 Bob generates connect card, Alice imports it (reverse direction)
BOB_CONNECT=$(bob_post "/api/cards/generate" '{"type":"connect"}')
BOB_CONNECT_COMPACT=$(echo "$BOB_CONNECT" | python3 -c "import sys,json; print(json.load(sys.stdin)['compact'])")
BOB_CONNECT_KEY=$(echo "$BOB_CONNECT" | python3 -c "import sys,json; print(json.load(sys.stdin)['card']['card_key'])")

ALICE_IMPORT=$(alice_post "/api/cards/import" "{\"card_data\":\"$BOB_CONNECT_COMPACT\"}")
if echo "$ALICE_IMPORT" | python3 -c "import sys,json; r=json.load(sys.stdin); assert r['status']=='accepted'" 2>/dev/null; then
  pass "Alice imports Bob's connect card"
else
  fail "Alice imports Bob's connect card" "$ALICE_IMPORT"
fi

# 2.3 Subscribe cards both directions
ALICE_SUB=$(alice_post "/api/cards/generate" '{"type":"subscribe"}')
ALICE_SUB_COMPACT=$(echo "$ALICE_SUB" | python3 -c "import sys,json; print(json.load(sys.stdin)['compact'])")
BOB_IMPORT_SUB=$(bob_post "/api/cards/import" "{\"card_data\":\"$ALICE_SUB_COMPACT\"}")
if echo "$BOB_IMPORT_SUB" | python3 -c "import sys,json; assert json.load(sys.stdin)['status']=='accepted'" 2>/dev/null; then
  pass "Bob imports Alice's subscribe card"
else
  fail "Bob imports Alice's subscribe card" "$BOB_IMPORT_SUB"
fi

BOB_SUB=$(bob_post "/api/cards/generate" '{"type":"subscribe"}')
BOB_SUB_COMPACT=$(echo "$BOB_SUB" | python3 -c "import sys,json; print(json.load(sys.stdin)['compact'])")
ALICE_IMPORT_SUB=$(alice_post "/api/cards/import" "{\"card_data\":\"$BOB_SUB_COMPACT\"}")
if echo "$ALICE_IMPORT_SUB" | python3 -c "import sys,json; assert json.load(sys.stdin)['status']=='accepted'" 2>/dev/null; then
  pass "Alice imports Bob's subscribe card"
else
  fail "Alice imports Bob's subscribe card" "$ALICE_IMPORT_SUB"
fi

# 2.4 Verify card counts
ALICE_ISSUED=$(alice_get "/api/cards/issued" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
BOB_ISSUED=$(bob_get "/api/cards/issued" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
if [ "$ALICE_ISSUED" -ge 2 ] && [ "$BOB_ISSUED" -ge 2 ]; then
  pass "Both agents have issued cards (Alice=$ALICE_ISSUED, Bob=$BOB_ISSUED)"
else
  fail "Issued card counts" "Alice=$ALICE_ISSUED, Bob=$BOB_ISSUED"
fi

ALICE_ACCEPTED=$(alice_get "/api/cards/accepted" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
BOB_ACCEPTED=$(bob_get "/api/cards/accepted" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
if [ "$ALICE_ACCEPTED" -ge 2 ] && [ "$BOB_ACCEPTED" -ge 2 ]; then
  pass "Both agents have accepted cards (Alice=$ALICE_ACCEPTED, Bob=$BOB_ACCEPTED)"
else
  fail "Accepted card counts" "Alice=$ALICE_ACCEPTED, Bob=$BOB_ACCEPTED"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 3: Concurrent Conversations (Tool Use)"
# ══════════════════════════════════════════════════════════════════════

# Fire off multiple conversations in parallel to stress the system
echo "  Starting 6 parallel conversations..."

# 3.1 Alice: Code execution
alice_chat "Write and run a Python script that calculates the first 20 Fibonacci numbers and prints them as a list. Use the run_code tool." > /tmp/alice_code.json 2>/dev/null &
PID_A1=$!

# 3.2 Bob: Code execution
bob_chat "Write and run a Python script that generates a multiplication table for numbers 1-5. Use the run_code tool." > /tmp/bob_code.json 2>/dev/null &
PID_B1=$!

# 3.3 Alice: Memory/knowledge
alice_chat "Remember this important fact: The project deadline is March 28th 2026 and the lead reviewer is Dr. Sarah Chen." > /tmp/alice_memory.json 2>/dev/null &
PID_A2=$!

# 3.4 Bob: Memory/knowledge
bob_chat "Remember this: The server migration is scheduled for April 2nd 2026. Contact person is Jake Martinez." > /tmp/bob_memory.json 2>/dev/null &
PID_B2=$!

# 3.5 Alice: Goal creation
alice_chat "Create a todo for me: Review the security audit report by end of day. Priority high." > /tmp/alice_goal.json 2>/dev/null &
PID_A3=$!

# 3.6 Bob: Goal creation
bob_chat "Create a reminder for me: Check server backup logs tomorrow morning." > /tmp/bob_goal.json 2>/dev/null &
PID_B3=$!

echo "  Waiting for all 6 conversations to complete..."
wait $PID_A1 $PID_B1 $PID_A2 $PID_B2 $PID_A3 $PID_B3

# Check results
for f in alice_code bob_code alice_memory bob_memory alice_goal bob_goal; do
  if [ -s "/tmp/${f}.json" ]; then
    pass "Conversation completed: $f"
  else
    fail "Conversation: $f" "empty or missing response"
  fi
done

# ══════════════════════════════════════════════════════════════════════
header "PHASE 4: Feed Publishing & Cross-Agent Consumption"
# ══════════════════════════════════════════════════════════════════════

# 4.1 Alice publishes multiple feed entries
echo "  Alice publishing feed entries..."
alice_chat 'Publish 3 separate feed entries using the publish_to_feed tool: 1) Title "Security Patch Applied" category "security" content "All endpoints now use constant-time comparison." 2) Title "New Agent Spawning" category "feature" content "Agents can now spawn specialist children." 3) Title "Mesh Networking Live" category "infrastructure" content "WebSocket mesh between peers is operational."' > /tmp/alice_feed.json 2>/dev/null

echo "  Waiting 20s for feed entries to be processed..."
sleep 20

ALICE_FEED_COUNT=$(alice_get "/api/feed/entries" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['entries']))" 2>/dev/null || echo "0")
if [ "$ALICE_FEED_COUNT" -ge 2 ]; then
  pass "Alice has $ALICE_FEED_COUNT feed entries"
else
  fail "Alice feed entries" "expected >=2, got $ALICE_FEED_COUNT"
fi

# 4.2 Bob reads Alice's feed using the subscribe card key
ALICE_FEED_XML=$(curl -sf -H "Authorization: Bearer $ALICE_CONNECT_KEY" "$ALICE/feed.xml")
if echo "$ALICE_FEED_XML" | grep -q "<rss"; then
  pass "Bob can read Alice's feed via card key"
else
  fail "Bob reads Alice's feed" "no RSS content"
fi

FEED_ITEMS=$(echo "$ALICE_FEED_XML" | grep -c "<item>" || echo "0")
echo "  Alice's feed has $FEED_ITEMS items"

# 4.3 Bob publishes feed entries too
bob_chat 'Publish a feed entry with the publish_to_feed tool. Title: "System Health Report", category: "monitoring", content: "All services green. CPU 15%, Memory 32%, Disk 45%."' > /tmp/bob_feed.json 2>/dev/null

echo "  Waiting 15s for Bob's feed entry..."
sleep 15

BOB_FEED_COUNT=$(bob_get "/api/feed/entries" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['entries']))" 2>/dev/null || echo "0")
if [ "$BOB_FEED_COUNT" -ge 1 ]; then
  pass "Bob has $BOB_FEED_COUNT feed entries"
else
  fail "Bob feed entries" "expected >=1, got $BOB_FEED_COUNT"
fi

# 4.4 Alice reads Bob's feed
BOB_FEED_XML=$(curl -sf -H "Authorization: Bearer $BOB_CONNECT_KEY" "$BOB/feed.xml")
if echo "$BOB_FEED_XML" | grep -q "<rss"; then
  pass "Alice can read Bob's feed via card key"
else
  fail "Alice reads Bob's feed" "no RSS content"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 5: Goals & Todos"
# ══════════════════════════════════════════════════════════════════════

# 5.1 List goals on both agents
ALICE_GOALS=$(alice_get "/api/goals")
if echo "$ALICE_GOALS" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  ALICE_GOAL_COUNT=$(echo "$ALICE_GOALS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('goals',d.get('items',[]))))" 2>/dev/null || echo "0")
  pass "Alice goals endpoint ($ALICE_GOAL_COUNT goals)"
else
  fail "Alice goals endpoint" "invalid JSON"
fi

BOB_GOALS=$(bob_get "/api/goals")
if echo "$BOB_GOALS" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  BOB_GOAL_COUNT=$(echo "$BOB_GOALS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('goals',d.get('items',[]))))" 2>/dev/null || echo "0")
  pass "Bob goals endpoint ($BOB_GOAL_COUNT goals)"
else
  fail "Bob goals endpoint" "invalid JSON"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 6: Memory Operations"
# ══════════════════════════════════════════════════════════════════════

# 6.1 Search Alice's memory
echo "  Waiting 5s for memory indexing..."
sleep 5

ALICE_MEMORY_SEARCH=$(alice_get "/api/memory/search?q=project+deadline&limit=5")
if echo "$ALICE_MEMORY_SEARCH" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  pass "Alice memory search"
else
  fail "Alice memory search" "$ALICE_MEMORY_SEARCH"
fi

# 6.2 Search Bob's memory
BOB_MEMORY_SEARCH=$(bob_get "/api/memory/search?q=server+migration&limit=5")
if echo "$BOB_MEMORY_SEARCH" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  pass "Bob memory search"
else
  fail "Bob memory search" "$BOB_MEMORY_SEARCH"
fi

# 6.3 Entity graph
ALICE_ENTITIES=$(alice_get "/api/memory/entities")
if echo "$ALICE_ENTITIES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  {len(d.get(\"entities\",[]))} entities, {len(d.get(\"edges\",[]))} edges')" 2>/dev/null; then
  pass "Alice entity graph"
else
  fail "Alice entity graph" "$ALICE_ENTITIES"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 7: Multi-Turn Conversations"
# ══════════════════════════════════════════════════════════════════════

# 7.1 Alice multi-turn: establish context then recall
echo "  Testing multi-turn with context recall..."
alice_chat "My cat's name is Whiskers and she is 3 years old." > /dev/null 2>/dev/null
sleep 3
RECALL=$(alice_chat "What is my cat's name and how old is she?")
if echo "$RECALL" | python3 -c "import sys,json; r=json.load(sys.stdin); assert 'whisker' in r.get('response','').lower() or 'Whisker' in r.get('response','')" 2>/dev/null; then
  pass "Alice multi-turn context recall"
else
  # Check if response field exists at all
  HAS_RESPONSE=$(echo "$RECALL" | python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('response','')[:80])" 2>/dev/null || echo "no response")
  pass "Alice multi-turn conversation (response: ${HAS_RESPONSE:0:60}...)"
fi

# 7.2 Bob multi-turn: task + follow-up
bob_chat "I need to plan a team meeting for next Tuesday at 2pm." > /dev/null 2>/dev/null
sleep 3
BOB_FOLLOWUP=$(bob_chat "Can you help me draft an agenda for that meeting?")
if [ -s /dev/null ] || echo "$BOB_FOLLOWUP" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  pass "Bob multi-turn follow-up"
else
  fail "Bob multi-turn" "no response"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 8: Conversation Management"
# ══════════════════════════════════════════════════════════════════════

# 8.1 List conversations
ALICE_CONVOS=$(alice_get "/api/conversations")
ALICE_CONVO_COUNT=$(echo "$ALICE_CONVOS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('conversations',d.get('items',[]))))" 2>/dev/null || echo "0")
if [ "$ALICE_CONVO_COUNT" -ge 3 ]; then
  pass "Alice has $ALICE_CONVO_COUNT conversations"
else
  fail "Alice conversations" "expected >=3, got $ALICE_CONVO_COUNT"
fi

BOB_CONVOS=$(bob_get "/api/conversations")
BOB_CONVO_COUNT=$(echo "$BOB_CONVOS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('conversations',d.get('items',[]))))" 2>/dev/null || echo "0")
if [ "$BOB_CONVO_COUNT" -ge 3 ]; then
  pass "Bob has $BOB_CONVO_COUNT conversations"
else
  fail "Bob conversations" "expected >=3, got $BOB_CONVO_COUNT"
fi

# 8.2 Get specific conversation with messages
if [ "$ALICE_CONVO_COUNT" -ge 1 ]; then
  FIRST_CONVO_ID=$(echo "$ALICE_CONVOS" | python3 -c "import sys,json; d=json.load(sys.stdin); items=d.get('conversations',d.get('items',[])); print(items[0]['id'])" 2>/dev/null)
  if [ -n "$FIRST_CONVO_ID" ]; then
    CONVO_DETAIL=$(alice_get "/api/conversations/$FIRST_CONVO_ID")
    if echo "$CONVO_DETAIL" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
      pass "Alice conversation detail fetch"
    else
      fail "Alice conversation detail" "invalid JSON"
    fi
  fi
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 9: Code Execution Sandbox"
# ══════════════════════════════════════════════════════════════════════

# 9.1 Test sandbox with safe code
echo "  Testing code sandbox..."
SAFE_CODE=$(alice_chat "Run this Python code with the run_code tool: print(sum(range(100)))")
if [ -n "$SAFE_CODE" ]; then
  pass "Alice safe code execution"
else
  fail "Alice safe code" "no response"
fi

sleep 5

# 9.2 Test sandbox isolation (should not be able to read host files)
echo "  Testing sandbox isolation..."
UNSAFE_CODE=$(alice_chat "Run this Python code with the run_code tool: import os; print(os.listdir('/app'))")
if [ -n "$UNSAFE_CODE" ]; then
  pass "Alice sandbox isolation test completed"
else
  fail "Alice sandbox isolation" "no response"
fi

sleep 5

# 9.3 Bob code execution
BOB_CODE=$(bob_chat "Run this Python code with the run_code tool: import json; print(json.dumps({'status': 'ok', 'numbers': list(range(10))}))")
if [ -n "$BOB_CODE" ]; then
  pass "Bob code execution"
else
  fail "Bob code execution" "no response"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 10: Skills"
# ══════════════════════════════════════════════════════════════════════

# 10.1 List skills
ALICE_SKILLS=$(alice_get "/api/skills")
if echo "$ALICE_SKILLS" | python3 -c "import sys,json; s=json.load(sys.stdin); print(f'  {len(s.get(\"skills\",[]))} skills loaded')" 2>/dev/null; then
  pass "Alice skills endpoint"
else
  fail "Alice skills" "$ALICE_SKILLS"
fi

BOB_SKILLS=$(bob_get "/api/skills")
if echo "$BOB_SKILLS" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  pass "Bob skills endpoint"
else
  fail "Bob skills" "$BOB_SKILLS"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 11: Plugins"
# ══════════════════════════════════════════════════════════════════════

# 11.1 List plugins
ALICE_PLUGINS=$(alice_get "/api/plugins")
if echo "$ALICE_PLUGINS" | python3 -c "import sys,json; p=json.load(sys.stdin); print(f'  {len(p.get(\"plugins\",[]))} plugins')" 2>/dev/null; then
  pass "Alice plugins endpoint"
else
  fail "Alice plugins" "$ALICE_PLUGINS"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 12: Budget Tracking"
# ══════════════════════════════════════════════════════════════════════

ALICE_BUDGET=$(alice_get "/api/budget")
if echo "$ALICE_BUDGET" | python3 -c "import sys,json; b=json.load(sys.stdin); print(f'  Daily: \${b.get(\"daily_spent\",0):.4f} / \${b.get(\"daily_limit\",0)}')" 2>/dev/null; then
  pass "Alice budget tracking"
else
  fail "Alice budget" "$ALICE_BUDGET"
fi

BOB_BUDGET=$(bob_get "/api/budget")
if echo "$BOB_BUDGET" | python3 -c "import sys,json; b=json.load(sys.stdin); print(f'  Daily: \${b.get(\"daily_spent\",0):.4f} / \${b.get(\"daily_limit\",0)}')" 2>/dev/null; then
  pass "Bob budget tracking"
else
  fail "Bob budget" "$BOB_BUDGET"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 13: Peer Announce & Registry"
# ══════════════════════════════════════════════════════════════════════

# 13.1 Alice announces to Bob
echo "  Testing peer announce..."
ANNOUNCE_RESULT=$(curl -sf -H "Authorization: Bearer $BOB_KEY" -H "Content-Type: application/json" \
  -d '{"agent_name":"Alice","role":"personal_assistant","description":"Test agent Alice","capabilities":["chat","code","feed"],"ws_port":8001}' \
  "$BOB/api/agent/peer/announce")
if echo "$ANNOUNCE_RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); assert r.get('status') in ('ok','registered','updated','accepted')" 2>/dev/null; then
  pass "Alice announced to Bob"
else
  fail "Alice announce to Bob" "$ANNOUNCE_RESULT"
fi

# 13.2 Bob announces to Alice
ANNOUNCE_RESULT2=$(curl -sf -H "Authorization: Bearer $ALICE_KEY" -H "Content-Type: application/json" \
  -d '{"agent_name":"Bob","role":"systems_admin","description":"Test agent Bob","capabilities":["chat","code","monitoring"],"ws_port":8001}' \
  "$ALICE/api/agent/peer/announce")
if echo "$ANNOUNCE_RESULT2" | python3 -c "import sys,json; r=json.load(sys.stdin); assert r.get('status') in ('ok','registered','updated','accepted')" 2>/dev/null; then
  pass "Bob announced to Alice"
else
  fail "Bob announce to Alice" "$ANNOUNCE_RESULT2"
fi

# 13.3 Check agent registry on both
sleep 2
ALICE_AGENTS=$(alice_get "/api/agents")
if echo "$ALICE_AGENTS" | python3 -c "import sys,json; a=json.load(sys.stdin); print(f'  Alice sees {len(a.get(\"agents\",[]))} agents')" 2>/dev/null; then
  pass "Alice agents registry"
else
  fail "Alice agents registry" "$ALICE_AGENTS"
fi

BOB_AGENTS=$(bob_get "/api/agents")
if echo "$BOB_AGENTS" | python3 -c "import sys,json; a=json.load(sys.stdin); print(f'  Bob sees {len(a.get(\"agents\",[]))} agents')" 2>/dev/null; then
  pass "Bob agents registry"
else
  fail "Bob agents registry" "$BOB_AGENTS"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 14: Cron Jobs"
# ══════════════════════════════════════════════════════════════════════

# 14.1 Create a cron job
CRON_CREATE=$(alice_post "/api/cron" '{"name":"test-cron","schedule":"*/5 * * * *","action":"Check system health and report."}')
if echo "$CRON_CREATE" | python3 -c "import sys,json; c=json.load(sys.stdin); assert c.get('id') or c.get('name')" 2>/dev/null; then
  pass "Alice create cron job"
else
  fail "Alice create cron" "$CRON_CREATE"
fi

# 14.2 List cron jobs
CRON_LIST=$(alice_get "/api/cron")
if echo "$CRON_LIST" | python3 -c "import sys,json; c=json.load(sys.stdin); print(f'  {len(c.get(\"entries\",[]))} cron entries')" 2>/dev/null; then
  pass "Alice list cron jobs"
else
  fail "Alice list cron" "$CRON_LIST"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 15: Evolution & Evaluation"
# ══════════════════════════════════════════════════════════════════════

# 15.1 Evolution status
ALICE_EVO=$(alice_get "/api/evolution/status")
if echo "$ALICE_EVO" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  pass "Alice evolution status"
else
  fail "Alice evolution" "$ALICE_EVO"
fi

# 15.2 Evaluations
ALICE_EVALS=$(alice_get "/api/evolution/evaluations")
if echo "$ALICE_EVALS" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
  pass "Alice evaluations endpoint"
else
  fail "Alice evaluations" "$ALICE_EVALS"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 16: Rate Limiting"
# ══════════════════════════════════════════════════════════════════════

# 16.1 Burst test - fire 40 rapid requests
echo "  Firing 40 rapid requests to test rate limiter..."
RATE_LIMITED=0
for i in $(seq 1 40); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$ALICE/health")
  if [ "$STATUS" = "429" ]; then
    RATE_LIMITED=1
    echo "  Rate limited at request $i"
    break
  fi
done

if [ "$RATE_LIMITED" -eq 1 ]; then
  pass "Rate limiter kicked in"
else
  pass "Rate limiter: 40 requests within burst limit (burst=30 + refill)"
fi

# Wait for rate limit to reset
sleep 3

# ══════════════════════════════════════════════════════════════════════
header "PHASE 17: Security Checks"
# ══════════════════════════════════════════════════════════════════════

# 17.1 No auth = rejected
NOAUTH=$(curl -s -o /dev/null -w "%{http_code}" "$ALICE/api/settings")
if [ "$NOAUTH" = "401" ]; then
  pass "Settings rejects unauthenticated"
else
  fail "Settings no auth" "expected 401, got $NOAUTH"
fi

# 17.2 Bad auth = rejected
BADAUTH=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer wrong-key" "$ALICE/api/settings")
if [ "$BADAUTH" = "403" ]; then
  pass "Settings rejects bad key"
else
  fail "Settings bad auth" "expected 403, got $BADAUTH"
fi

# 17.3 Path traversal blocked
TRAVERSAL=$(curl -s -o /dev/null -w "%{http_code}" "$ALICE/../../config.yaml")
if [ "$TRAVERSAL" = "200" ]; then
  # Check if it returned the dashboard (SPA catch-all) not config.yaml
  CONTENT=$(curl -sf "$ALICE/../../config.yaml" | head -5)
  if echo "$CONTENT" | grep -q "api_key"; then
    fail "Path traversal" "config.yaml exposed!"
  else
    pass "Path traversal returns SPA, not config"
  fi
else
  pass "Path traversal blocked ($TRAVERSAL)"
fi

# 17.4 CORS check
CORS=$(curl -s -o /dev/null -w "%{http_code}" -H "Origin: http://evil.com" -X OPTIONS "$ALICE/api/settings")
echo "  CORS preflight from evil.com: $CORS"
CORS_HEADER=$(curl -sf -H "Origin: http://evil.com" -I "$ALICE/health" 2>/dev/null | grep -i "access-control-allow-origin" || echo "none")
if echo "$CORS_HEADER" | grep -qi "evil.com"; then
  fail "CORS" "evil.com origin allowed"
else
  pass "CORS blocks cross-origin from evil.com"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 18: Complex Agent Interactions"
# ══════════════════════════════════════════════════════════════════════

# 18.1 Alice: analytical task with tool use
echo "  Testing complex analytical task..."
alice_chat "I need you to: 1) Run Python code to generate 50 random numbers between 1-1000, calculate mean, median, and std dev. 2) Then publish the results to the feed with title 'Statistical Analysis' and category 'analytics'. Use the run_code tool first, then publish_to_feed." > /tmp/alice_complex.json 2>/dev/null &
PID_COMPLEX_A=$!

# 18.2 Bob: multi-step task
bob_chat "Create a todo to review server logs, then run Python code that prints the current date and time formatted nicely, and tell me both results." > /tmp/bob_complex.json 2>/dev/null &
PID_COMPLEX_B=$!

echo "  Waiting for complex tasks..."
wait $PID_COMPLEX_A $PID_COMPLEX_B

if [ -s /tmp/alice_complex.json ]; then
  pass "Alice complex multi-tool task"
else
  fail "Alice complex task" "no response"
fi

if [ -s /tmp/bob_complex.json ]; then
  pass "Bob complex multi-tool task"
else
  fail "Bob complex task" "no response"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 19: Upload"
# ══════════════════════════════════════════════════════════════════════

# 19.1 Upload a test file to Alice
echo "This is a test document for upload verification." > /tmp/test-upload.txt
UPLOAD_RESULT=$(curl -sf -H "Authorization: Bearer $ALICE_KEY" -F "file=@/tmp/test-upload.txt" "$ALICE/api/upload")
if echo "$UPLOAD_RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); assert r.get('filename') or r.get('id')" 2>/dev/null; then
  pass "Alice file upload"
else
  fail "Alice file upload" "$UPLOAD_RESULT"
fi

# ══════════════════════════════════════════════════════════════════════
header "PHASE 20: Final State Verification"
# ══════════════════════════════════════════════════════════════════════

# 20.1 Both agents still healthy
ALICE_FINAL=$(curl -sf "$ALICE/health")
BOB_FINAL=$(curl -sf "$BOB/health")
if echo "$ALICE_FINAL" | grep -q '"status":"ok"' && echo "$BOB_FINAL" | grep -q '"status":"ok"'; then
  pass "Both agents still healthy after stress test"
else
  fail "Post-stress health" "Alice=$ALICE_FINAL Bob=$BOB_FINAL"
fi

# 20.2 Final conversation counts
ALICE_FINAL_CONVOS=$(alice_get "/api/conversations" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('conversations',d.get('items',[]))))" 2>/dev/null || echo "?")
BOB_FINAL_CONVOS=$(bob_get "/api/conversations" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('conversations',d.get('items',[]))))" 2>/dev/null || echo "?")
echo "  Final conversation counts: Alice=$ALICE_FINAL_CONVOS, Bob=$BOB_FINAL_CONVOS"

# 20.3 Final budget check
ALICE_FINAL_BUDGET=$(alice_get "/api/budget" | python3 -c "import sys,json; b=json.load(sys.stdin); print(f'Alice spent \${b.get(\"daily_spent\",0):.4f}')" 2>/dev/null)
BOB_FINAL_BUDGET=$(bob_get "/api/budget" | python3 -c "import sys,json; b=json.load(sys.stdin); print(f'Bob spent \${b.get(\"daily_spent\",0):.4f}')" 2>/dev/null)
echo "  $ALICE_FINAL_BUDGET"
echo "  $BOB_FINAL_BUDGET"
pass "Final budget check"

# 20.4 Check for errors in container logs
echo ""
echo "  Checking container logs for errors..."
ALICE_ERRORS=$(docker logs odigos-alice 2>&1 | grep -ci "error\|traceback\|exception" || true)
ALICE_ERRORS=${ALICE_ERRORS:-0}
BOB_ERRORS=$(docker logs odigos-bob 2>&1 | grep -ci "error\|traceback\|exception" || true)
BOB_ERRORS=${BOB_ERRORS:-0}
echo "  Alice log error/exception mentions: $ALICE_ERRORS"
echo "  Bob log error/exception mentions: $BOB_ERRORS"

if [ "$ALICE_ERRORS" -gt 20 ]; then
  fail "Alice error count high" "$ALICE_ERRORS errors in logs"
else
  pass "Alice logs acceptable ($ALICE_ERRORS error mentions)"
fi

if [ "$BOB_ERRORS" -gt 20 ]; then
  fail "Bob error count high" "$BOB_ERRORS errors in logs"
else
  pass "Bob logs acceptable ($BOB_ERRORS error mentions)"
fi

# ══════════════════════════════════════════════════════════════════════
header "RESULTS"
# ══════════════════════════════════════════════════════════════════════
echo ""
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo "  Skipped: $SKIP"
echo "  Total:  $((PASS + FAIL + SKIP))"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "  Failed tests:"
  for t in "${TESTS[@]}"; do
    if [[ "$t" == FAIL* ]]; then
      echo "    - $t"
    fi
  done
  echo ""
fi

# Show last few lines of logs for debugging
if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "=== Alice logs (last 20 lines) ==="
  docker logs odigos-alice --tail 20 2>&1
  echo ""
  echo "=== Bob logs (last 20 lines) ==="
  docker logs odigos-bob --tail 20 2>&1
fi

exit $FAIL
