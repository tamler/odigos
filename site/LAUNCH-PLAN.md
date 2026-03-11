# Odigos Consultancy — Launch Plan

**Date:** March 10, 2026
**Goal:** Taking clients within 72 hours

---

## Positioning

**One-liner:** Odigos designs and builds AI systems that remember, act, and improve.

**Elevator pitch (30 seconds):**
"Most companies trying to adopt AI end up with either a chatbot that forgets everything between sessions, or a fragile agent framework that breaks in production. I design and build AI systems that actually work — agents that remember context, take real actions, and get better over time. I've been doing this since before ChatGPT existed, and I bring a UX designer's eye to every system I build. The result is AI that people actually use."

**Differentiator:** UX + systems design + pre-LLM AI experience. You don't just build the tech, you make it usable. Most AI consultants can do one or the other.

**Proof of capability:** Odigos agent system — a working, self-hosted AI agent with memory, tools, and self-improvement. Not a demo, not a prototype, a system that runs in production.

---

## Service Tiers & Pricing

### Tier 1: AI Strategy & Assessment
**What:** Audit existing workflows, identify AI opportunities, deliver a prioritized roadmap.
**Deliverable:** Written roadmap with specific recommendations, ranked by impact/feasibility.
**Duration:** 1-2 weeks
**Pricing:**
- Local (Cebu/PH): ₱75,000 - ₱150,000 (~$1,300 - $2,600)
- International: $3,500 - $7,500

### Tier 2: Agent & Assistant Development
**What:** Design and build custom AI agents/assistants integrated with client's tools.
**Deliverable:** Working system deployed on client's infrastructure, with documentation.
**Duration:** 4-12 weeks depending on scope
**Pricing:**
- Local: ₱200,000 - ₱750,000 (~$3,500 - $13,000)
- International: $10,000 - $50,000+

### Tier 3: AI Experience Design
**What:** UX design for AI products — conversation design, interaction patterns, trust/safety.
**Deliverable:** Design specs, prototypes, interaction models.
**Duration:** 2-6 weeks
**Pricing:**
- Local: ₱100,000 - ₱350,000 (~$1,750 - $6,000)
- International: $5,000 - $15,000

### Tier 4: Advisory Retainer
**What:** Monthly access — architecture reviews, prompt engineering, vendor eval, strategy.
**Deliverable:** Ongoing support, weekly check-ins, async availability.
**Duration:** Monthly (3-month minimum)
**Pricing:**
- Local: ₱50,000/mo (~$870/mo)
- International: $3,000 - $5,000/mo

### Pricing notes:
- These are starting ranges. Adjust based on what the market tells you.
- For the first 2-3 clients, consider discounting 20-30% in exchange for a case study / testimonial.
- "Local discount" positions you as accessible to the Cebu tech ecosystem while international rates reflect the real value.
- Always scope projects with a fixed price AND a time estimate. Clients prefer certainty.

---

## The Agent-Powered Contact Flow

This is what makes Odigos different from every other consultancy site.

### Architecture

```
Prospect visits odigos.one
        │
        ▼
  Clicks "Message us on Telegram"
        │
        ▼
┌─────────────────────────────────┐
│     ODIGOS SALES AGENT          │
│  (Telegram bot, separate from   │
│   your personal Odigos agent)   │
│                                 │
│  - Greets prospect              │
│  - Asks about their needs       │
│  - Explains services            │
│  - Qualifies the lead           │
│  - Schedules a call with Jacob  │
│  - Sends Jacob a summary        │
│                                 │
│  Backed by: Odigos codebase     │
│  With: Sales-specific skills    │
│  Memory: Remembers returning    │
│          prospects              │
└─────────────────────────────────┘
        │
        ▼
  Jacob gets a Telegram message:
  "New lead: [name], [company], [need].
   They booked a call for [time].
   Summary: [3 sentences]"
```

### Why this works:
1. **Immediate proof of capability.** The prospect's first interaction IS an AI agent. They experience what you build before you ever pitch them.
2. **24/7 availability.** You're in Cebu. Prospects in the US/UK are in different timezones. The agent is always on.
3. **Pre-qualification.** By the time you get on a call, the agent has already gathered context. No wasted discovery calls.
4. **Memory.** If a prospect comes back 2 weeks later, the agent remembers them. That's the "memory is the product" principle in action.

### Implementation priority:
1. **Day 1:** Deploy a basic version — Odigos agent with a sales-focused personality and skill set. It answers questions about services and takes contact info.
2. **Day 3-5:** Add Google Calendar integration so it can actually book calls.
3. **Week 2:** Add lead qualification logic — ask about budget, timeline, team size. Route serious leads differently from tire-kickers.

### Demo instance for prospects:
For serious prospects (post-call), spin up a temporary Odigos instance:
- Fresh VPS (use a lightweight provisioning script)
- Pre-loaded with a demo personality and sample data
- 7-day trial period
- Prospect interacts with their own agent via Telegram
- Shows the product better than any slide deck ever could

---

## 72-Hour Launch Checklist

### Day 1 (Today — March 10)
- [ ] Register odigos.one domain (if not already done)
- [ ] Set up DNS pointing to a VPS or static host (Cloudflare Pages, Vercel, or Netlify for the static site)
- [ ] Deploy the landing page
- [ ] Set up jacob@odigos.one email (Google Workspace or Zoho free tier)
- [ ] Create a Telegram bot for the sales agent (@OdigosBot or @OdigosAgent)
- [ ] Deploy a basic Odigos instance configured as a sales agent
- [ ] Update LinkedIn headline to "Founder, Odigos — AI Systems That Actually Work"
- [ ] Post on LinkedIn: "I just launched Odigos..." (announcement post)

### Day 2 (March 11)
- [ ] Test the full flow: visit site → Telegram → agent responds → you get notified
- [ ] Write 3-5 LinkedIn posts to schedule over the next week (AI + UX + agent systems content)
- [ ] Identify 10 local Cebu businesses/startups that could benefit from AI
- [ ] Join local tech communities (Cebu tech groups, PH startup Slack/Discord channels)
- [ ] Set up Google Analytics or Plausible on the landing page
- [ ] Record a 60-second Loom: "What Odigos does" — embed on site or share on social

### Day 3 (March 12)
- [ ] Send 5 direct outreach messages to Cebu-based contacts
- [ ] Post first LinkedIn content piece
- [ ] Ensure the sales agent handles the top 10 questions a prospect would ask
- [ ] Set up a simple CRM (even a Google Sheet: Name, Company, Need, Stage, Next Action)
- [ ] Write a "How I Built an AI Agent in a Week" blog post (great for credibility)

### Week 1 follow-up:
- [ ] Apply to 2-3 freelance platforms (Toptal, Upwork — for pipeline, not as primary channel)
- [ ] Reach out to 24/7.ai network for referrals
- [ ] Consider a "free AI assessment" offer for the first 3 local companies (builds case studies)
- [ ] Start documenting everything — this becomes content AND case studies

---

## Content Strategy (Ongoing)

Your content should demonstrate expertise, not just claim it. Topics:

1. **"Why your chatbot isn't an agent"** — explains the memory/action gap
2. **"The $50/month AI assistant"** — Odigos cost breakdown, shows you think about real economics
3. **"Designing AI that people actually use"** — your UX + AI intersection, unique angle
4. **"What I learned building agent systems before LLMs"** — credibility from 24/7.ai era
5. **"The lean agent architecture"** — technical content for engineering-minded prospects
6. **Build-in-public updates** — weekly progress on Odigos, shows continuous capability growth

Post cadence: 3x/week on LinkedIn minimum. Mix of insight posts, build updates, and opinions.

---

## Key Decisions Still Needed

1. **Domain registrar:** Where are you buying/managing odigos.one?
2. **Hosting:** Where does the landing page live? (Cloudflare Pages is free and fast)
3. **Email:** Google Workspace (~$6/mo) vs Zoho free tier for jacob@odigos.one?
4. **Telegram bot name:** @OdigosBot? @OdigosAgent? @AskOdigos?
5. **LinkedIn URL:** Can you get linkedin.com/in/odigos or similar?
6. **Legal entity:** Do you need a registered business in PH? (Can operate as sole proprietor initially)

---

## What Success Looks Like

**Week 1:** Site live, agent responding, 3+ conversations with potential clients
**Month 1:** 1-2 paying clients (even small projects), 3+ active prospects in pipeline
**Month 3:** Consistent pipeline, 1-2 active projects, first case study published, first freelancer brought on
**Month 6:** Profitable, 3-4 concurrent projects, Odigos open-sourced (community = marketing), recognized locally as "the AI person"
