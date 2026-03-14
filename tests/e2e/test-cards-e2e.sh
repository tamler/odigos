#!/usr/bin/env bash
# End-to-end test for contact cards, feed publisher, mesh, and agent capabilities.
#
# Prerequisites:
#   LLM_API_KEY=your-key docker compose -f docker-compose.test.yml up --build -d
#   Wait for both agents to be healthy:
#   docker compose -f docker-compose.test.yml ps
#
# Usage:
#   bash tests/e2e/test-cards-e2e.sh

set -euo pipefail

ALICE="http://localhost:8100"
BOB="http://localhost:8200"
ALICE_KEY="alice-test-key"
BOB_KEY="bob-test-key"

PASS=0
FAIL=0
TESTS=()

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); TESTS+=("PASS: $1"); }
fail() { echo "  FAIL: $1 -- $2"; FAIL=$((FAIL + 1)); TESTS+=("FAIL: $1"); }

header() { echo ""; echo "=== $1 ==="; }

# ── Helpers ──────────────────────────────────────────────────────────

alice_get()  { curl -sf -H "Authorization: Bearer $ALICE_KEY" "$ALICE$1"; }
alice_post() { curl -sf -H "Authorization: Bearer $ALICE_KEY" -H "Content-Type: application/json" -d "$2" "$ALICE$1"; }
alice_del()  { curl -sf -X DELETE -H "Authorization: Bearer $ALICE_KEY" "$ALICE$1"; }

bob_get()  { curl -sf -H "Authorization: Bearer $BOB_KEY" "$BOB$1"; }
bob_post() { curl -sf -H "Authorization: Bearer $BOB_KEY" -H "Content-Type: application/json" -d "$2" "$BOB$1"; }

# ── Wait for health ─────────────────────────────────────────────────

header "Waiting for agents to be healthy"

for agent in "$ALICE" "$BOB"; do
  name=$([ "$agent" = "$ALICE" ] && echo "Alice" || echo "Bob")
  for i in $(seq 1 60); do
    if curl -sf "$agent/health" > /dev/null 2>&1; then
      echo "  $name is healthy"
      break
    fi
    if [ "$i" -eq 60 ]; then
      echo "  FATAL: $name did not become healthy after 60 attempts"
      exit 1
    fi
    sleep 2
  done
done

# ── 1. Health check ──────────────────────────────────────────────────

header "1. Health Checks"

ALICE_HEALTH=$(curl -sf "$ALICE/health")
if echo "$ALICE_HEALTH" | grep -q '"status":"ok"'; then
  pass "Alice health check"
else
  fail "Alice health check" "$ALICE_HEALTH"
fi

BOB_HEALTH=$(curl -sf "$BOB/health")
if echo "$BOB_HEALTH" | grep -q '"status":"ok"'; then
  pass "Bob health check"
else
  fail "Bob health check" "$BOB_HEALTH"
fi

# ── 2. Settings API (verify feed + mesh config) ─────────────────────

header "2. Settings Verification"

ALICE_SETTINGS=$(alice_get "/api/settings")
if echo "$ALICE_SETTINGS" | python3 -c "import sys,json; s=json.load(sys.stdin); assert s['mesh']['enabled']==True; assert s['feed']['enabled']==True" 2>/dev/null; then
  pass "Alice mesh+feed enabled"
else
  fail "Alice mesh+feed settings" "mesh or feed not enabled"
fi

BOB_SETTINGS=$(bob_get "/api/settings")
if echo "$BOB_SETTINGS" | python3 -c "import sys,json; s=json.load(sys.stdin); assert s['mesh']['enabled']==True; assert s['feed']['enabled']==True" 2>/dev/null; then
  pass "Bob mesh+feed enabled"
else
  fail "Bob mesh+feed settings" "mesh or feed not enabled"
fi

# ── 3. Generate connect card on Alice ────────────────────────────────

header "3. Card Generation"

CONNECT_CARD=$(alice_post "/api/cards/generate" '{"type":"connect"}')
if echo "$CONNECT_CARD" | python3 -c "import sys,json; c=json.load(sys.stdin); assert c['card']['type']=='connect'; assert c['card']['card_key'].startswith('card-sk-')" 2>/dev/null; then
  pass "Alice generate connect card"
else
  fail "Alice generate connect card" "$CONNECT_CARD"
fi

CONNECT_COMPACT=$(echo "$CONNECT_CARD" | python3 -c "import sys,json; print(json.load(sys.stdin)['compact'])")
CONNECT_CARD_KEY=$(echo "$CONNECT_CARD" | python3 -c "import sys,json; print(json.load(sys.stdin)['card']['card_key'])")

# Generate subscribe card
SUBSCRIBE_CARD=$(alice_post "/api/cards/generate" '{"type":"subscribe"}')
if echo "$SUBSCRIBE_CARD" | python3 -c "import sys,json; c=json.load(sys.stdin); assert c['card']['type']=='subscribe'; assert c['card']['feed_url'] is not None" 2>/dev/null; then
  pass "Alice generate subscribe card"
else
  fail "Alice generate subscribe card" "$SUBSCRIBE_CARD"
fi

SUBSCRIBE_CARD_KEY=$(echo "$SUBSCRIBE_CARD" | python3 -c "import sys,json; print(json.load(sys.stdin)['card']['card_key'])")
SUBSCRIBE_COMPACT=$(echo "$SUBSCRIBE_CARD" | python3 -c "import sys,json; print(json.load(sys.stdin)['compact'])")

# Generate invite card
INVITE_CARD=$(alice_post "/api/cards/generate" '{"type":"invite"}')
if echo "$INVITE_CARD" | python3 -c "import sys,json; c=json.load(sys.stdin); assert c['card']['type']=='invite'" 2>/dev/null; then
  pass "Alice generate invite card"
else
  fail "Alice generate invite card" "$INVITE_CARD"
fi

# Generate card with expiry
EXPIRY_CARD=$(alice_post "/api/cards/generate" '{"type":"connect","expires_in_days":7}')
if echo "$EXPIRY_CARD" | python3 -c "import sys,json; c=json.load(sys.stdin); assert c['card']['expires_at'] is not None" 2>/dev/null; then
  pass "Alice generate card with expiry"
else
  fail "Alice generate card with expiry" "$EXPIRY_CARD"
fi

# ── 4. List issued cards on Alice ────────────────────────────────────

header "4. List Issued Cards"

ISSUED=$(alice_get "/api/cards/issued")
ISSUED_COUNT=$(echo "$ISSUED" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
if [ "$ISSUED_COUNT" -ge 4 ]; then
  pass "Alice has $ISSUED_COUNT issued cards"
else
  fail "Alice issued cards count" "expected >=4, got $ISSUED_COUNT"
fi

# ── 5. Import connect card on Bob ────────────────────────────────────

header "5. Card Import"

IMPORT_RESULT=$(bob_post "/api/cards/import" "{\"card_data\":\"$CONNECT_COMPACT\"}")
if echo "$IMPORT_RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); assert r['status']=='accepted'; assert r['agent_name']=='Alice'" 2>/dev/null; then
  pass "Bob import connect card from Alice"
else
  fail "Bob import connect card" "$IMPORT_RESULT"
fi

# Import subscribe card on Bob
IMPORT_SUB=$(bob_post "/api/cards/import" "{\"card_data\":\"$SUBSCRIBE_COMPACT\"}")
if echo "$IMPORT_SUB" | python3 -c "import sys,json; r=json.load(sys.stdin); assert r['status']=='accepted'" 2>/dev/null; then
  pass "Bob import subscribe card from Alice"
else
  fail "Bob import subscribe card" "$IMPORT_SUB"
fi

# ── 6. List accepted cards on Bob ────────────────────────────────────

header "6. List Accepted Cards"

ACCEPTED=$(bob_get "/api/cards/accepted")
ACCEPTED_COUNT=$(echo "$ACCEPTED" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['cards']))")
if [ "$ACCEPTED_COUNT" -ge 2 ]; then
  pass "Bob has $ACCEPTED_COUNT accepted cards"
else
  fail "Bob accepted cards count" "expected >=2, got $ACCEPTED_COUNT"
fi

ACCEPTED_CONNECT_ID=$(echo "$ACCEPTED" | python3 -c "import sys,json; cards=json.load(sys.stdin)['cards']; print([c['id'] for c in cards if c['card_type']=='connect'][0])")
ACCEPTED_SUBSCRIBE_ID=$(echo "$ACCEPTED" | python3 -c "import sys,json; cards=json.load(sys.stdin)['cards']; print([c['id'] for c in cards if c['card_type']=='subscribe'][0])")

# ── 7. Tampered card rejection ───────────────────────────────────────

header "7. Card Security"

# Try importing a card with tampered fingerprint
TAMPERED=$(alice_post "/api/cards/generate" '{"type":"connect"}')
TAMPERED_YAML=$(echo "$TAMPERED" | python3 -c "
import sys, json, yaml, base64
card = json.load(sys.stdin)['card']
card['fingerprint'] = 'sha256:tampered'
print('odigos-card:' + base64.b64encode(yaml.dump(card).encode()).decode())
")
TAMPER_RESULT=$(bob_post "/api/cards/import" "{\"card_data\":\"$TAMPERED_YAML\"}")
if echo "$TAMPER_RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); assert r['status']=='rejected'; assert 'fingerprint' in r.get('reason','').lower()" 2>/dev/null; then
  pass "Tampered card rejected"
else
  fail "Tampered card rejection" "$TAMPER_RESULT"
fi

# Try importing garbage
GARBAGE_RESULT=$(bob_post "/api/cards/import" '{"card_data":"not-a-card"}')
if echo "$GARBAGE_RESULT" | python3 -c "import sys,json; r=json.load(sys.stdin); assert r['status']=='rejected'" 2>/dev/null; then
  pass "Garbage card data rejected"
else
  fail "Garbage card rejection" "$GARBAGE_RESULT"
fi

# ── 8. Feed publishing ───────────────────────────────────────────────

header "8. Feed Publishing"

# Alice sends a message asking to publish to feed
PUBLISH_MSG=$(alice_post "/api/message" '{"content":"Please publish a feed entry with title \"System Status Update\" and content \"All systems operational. CPU at 23%, memory at 45%.\" in category \"status\". Use the publish_to_feed tool."}')
if [ $? -eq 0 ]; then
  pass "Alice publish-to-feed message sent"
else
  fail "Alice publish-to-feed message" "API call failed"
fi

# Wait for agent to process
echo "  Waiting 15s for agent to process publish request..."
sleep 15

# Check feed entries on Alice
FEED_ENTRIES=$(alice_get "/api/feed/entries")
FEED_COUNT=$(echo "$FEED_ENTRIES" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['entries']))" 2>/dev/null || echo "0")
if [ "$FEED_COUNT" -ge 1 ]; then
  pass "Alice has $FEED_COUNT feed entries"
else
  # Publish directly via API as fallback (agent may not have processed yet)
  echo "  Agent hasn't published yet, trying direct tool approach..."
  # We'll check again after more tests
  fail "Alice feed entries" "expected >=1, got $FEED_COUNT (agent may still be processing)"
fi

# ── 9. Feed XML endpoint ─────────────────────────────────────────────

header "9. Feed XML Endpoint"

# Private feed without auth should fail
FEED_NOAUTH=$(curl -s -o /dev/null -w "%{http_code}" "$ALICE/feed.xml")
if [ "$FEED_NOAUTH" = "401" ]; then
  pass "Private feed rejects unauthenticated requests"
else
  fail "Private feed auth" "expected 401, got $FEED_NOAUTH"
fi

# Feed with global API key should work
FEED_GLOBAL=$(curl -sf -H "Authorization: Bearer $ALICE_KEY" "$ALICE/feed.xml")
if echo "$FEED_GLOBAL" | grep -q "<rss"; then
  pass "Feed accessible with global API key"
else
  fail "Feed with global key" "no RSS content returned"
fi

# Feed with subscribe card key should work
FEED_CARD=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $SUBSCRIBE_CARD_KEY" "$ALICE/feed.xml")
if [ "$FEED_CARD" = "200" ]; then
  pass "Feed accessible with subscribe card key"
else
  fail "Feed with subscribe card key" "expected 200, got $FEED_CARD"
fi

# Feed with connect card key should also work
FEED_CONNECT=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $CONNECT_CARD_KEY" "$ALICE/feed.xml")
if [ "$FEED_CONNECT" = "200" ]; then
  pass "Feed accessible with connect card key"
else
  fail "Feed with connect card key" "expected 200, got $FEED_CONNECT"
fi

# Feed with invalid key should fail
FEED_BAD=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer bad-key" "$ALICE/feed.xml")
if [ "$FEED_BAD" = "403" ]; then
  pass "Feed rejects invalid card key"
else
  fail "Feed with invalid key" "expected 403, got $FEED_BAD"
fi

# ── 10. Mute / Unmute ────────────────────────────────────────────────

header "10. Mute / Unmute"

MUTE_RESULT=$(bob_post "/api/cards/accepted/$ACCEPTED_CONNECT_ID/mute" '{}')
if echo "$MUTE_RESULT" | grep -q '"status":"ok"'; then
  pass "Bob muted Alice's connect card"
else
  fail "Bob mute card" "$MUTE_RESULT"
fi

# Verify status changed
MUTED_STATUS=$(bob_get "/api/cards/accepted" | python3 -c "import sys,json; cards=json.load(sys.stdin)['cards']; print([c['status'] for c in cards if c['id']=='$ACCEPTED_CONNECT_ID'][0])")
if [ "$MUTED_STATUS" = "muted" ]; then
  pass "Card status is muted"
else
  fail "Muted card status" "expected muted, got $MUTED_STATUS"
fi

UNMUTE_RESULT=$(bob_post "/api/cards/accepted/$ACCEPTED_CONNECT_ID/unmute" '{}')
if echo "$UNMUTE_RESULT" | grep -q '"status":"ok"'; then
  pass "Bob unmuted Alice's connect card"
else
  fail "Bob unmute card" "$UNMUTE_RESULT"
fi

UNMUTED_STATUS=$(bob_get "/api/cards/accepted" | python3 -c "import sys,json; cards=json.load(sys.stdin)['cards']; print([c['status'] for c in cards if c['id']=='$ACCEPTED_CONNECT_ID'][0])")
if [ "$UNMUTED_STATUS" = "active" ]; then
  pass "Card status restored to active"
else
  fail "Unmuted card status" "expected active, got $UNMUTED_STATUS"
fi

# ── 11. Revocation ───────────────────────────────────────────────────

header "11. Revocation"

# Alice revokes the connect card she issued
REVOKE_ISSUED=$(alice_post "/api/cards/issued/$CONNECT_CARD_KEY/revoke" '{}')
if echo "$REVOKE_ISSUED" | grep -q '"status":"ok"'; then
  pass "Alice revoked connect card"
else
  fail "Alice revoke issued card" "$REVOKE_ISSUED"
fi

# The connect card key should no longer work for feed access
FEED_REVOKED=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $CONNECT_CARD_KEY" "$ALICE/feed.xml")
if [ "$FEED_REVOKED" = "403" ]; then
  pass "Revoked card key rejected for feed access"
else
  fail "Revoked card feed access" "expected 403, got $FEED_REVOKED"
fi

# Bob can also revoke his accepted card
REVOKE_ACCEPTED=$(bob_post "/api/cards/accepted/$ACCEPTED_SUBSCRIBE_ID/revoke" '{}')
if echo "$REVOKE_ACCEPTED" | grep -q '"status":"ok"'; then
  pass "Bob revoked accepted subscribe card"
else
  fail "Bob revoke accepted card" "$REVOKE_ACCEPTED"
fi

# ── 12. Agent conversation test ──────────────────────────────────────

header "12. Agent Conversation (LLM)"

# Send a simple message to Alice and verify she responds
CONV_RESULT=$(alice_post "/api/message" '{"content":"What is your name? Reply in one short sentence."}')
if [ $? -eq 0 ]; then
  pass "Alice accepts conversation message"
else
  fail "Alice conversation" "API call failed"
fi

# Wait for response
echo "  Waiting 10s for LLM response..."
sleep 10

# Check conversations
CONVOS=$(alice_get "/api/conversations")
CONVO_COUNT=$(echo "$CONVOS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('conversations',d.get('items',[]))))" 2>/dev/null || echo "0")
if [ "$CONVO_COUNT" -ge 1 ]; then
  pass "Alice has $CONVO_COUNT conversations"
else
  fail "Alice conversations" "expected >=1, got $CONVO_COUNT"
fi

# ── 13. Template browsing ────────────────────────────────────────────

header "13. Agent Template Browsing"

TEMPLATE_MSG=$(alice_post "/api/message" '{"content":"Browse the agent templates catalog and tell me what categories of agents are available. Use the browse_templates tool with keyword \"all\"."}')
if [ $? -eq 0 ]; then
  pass "Template browse message sent"
else
  fail "Template browse" "API call failed"
fi

echo "  Waiting 15s for template browsing..."
sleep 15

# ── 14. Feed deletion ────────────────────────────────────────────────

header "14. Feed Entry Management"

# List current entries
ENTRIES=$(alice_get "/api/feed/entries")
ENTRY_COUNT=$(echo "$ENTRIES" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['entries']))" 2>/dev/null || echo "0")
echo "  Alice has $ENTRY_COUNT feed entries"

if [ "$ENTRY_COUNT" -ge 1 ]; then
  ENTRY_ID=$(echo "$ENTRIES" | python3 -c "import sys,json; print(json.load(sys.stdin)['entries'][0]['id'])")
  DEL_RESULT=$(alice_del "/api/feed/entries/$ENTRY_ID")
  if echo "$DEL_RESULT" | grep -q '"status":"ok"'; then
    pass "Delete feed entry"
  else
    fail "Delete feed entry" "$DEL_RESULT"
  fi
else
  echo "  Skipping delete test (no entries to delete)"
fi

# ── 15. Dashboard build verification ─────────────────────────────────

header "15. Dashboard Accessibility"

DASHBOARD=$(curl -s -o /dev/null -w "%{http_code}" "$ALICE/")
if [ "$DASHBOARD" = "200" ]; then
  pass "Alice dashboard accessible"
else
  fail "Alice dashboard" "expected 200, got $DASHBOARD"
fi

BOB_DASHBOARD=$(curl -s -o /dev/null -w "%{http_code}" "$BOB/")
if [ "$BOB_DASHBOARD" = "200" ]; then
  pass "Bob dashboard accessible"
else
  fail "Bob dashboard" "expected 200, got $BOB_DASHBOARD"
fi

# ── Summary ──────────────────────────────────────────────────────────

header "RESULTS"
echo ""
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo "  Total:  $((PASS + FAIL))"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "  Failed tests:"
  for t in "${TESTS[@]}"; do
    if [[ "$t" == FAIL* ]]; then
      echo "    - $t"
    fi
  done
  echo ""
  exit 1
fi

echo "  All tests passed!"
