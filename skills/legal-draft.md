---
name: legal-draft
description: Generate legal documents -- NDAs, terms of service, privacy policies, freelancer contracts, business agreements
tools: [create_artifact, analyze_text, lookup]
complexity: standard
---

# Legal Document Drafting

When the user asks you to create a legal document, generate a professional, comprehensive draft tailored to their specific situation.

## Supported Document Types

### NDA (Non-Disclosure Agreement)
Ask for: parties, purpose, duration, jurisdiction, mutual or one-way.
Include: definition of confidential information, exclusions (public knowledge, independent development, prior knowledge), obligations, permitted disclosures (legal compulsion), term and survival, remedies (injunctive relief), return/destruction of materials.

### Terms of Service
Ask for: business type, service description, jurisdiction, payment model.
Include: acceptance mechanism, user obligations, prohibited conduct, IP ownership, user content license, disclaimers (AS-IS), limitation of liability (cap at fees paid), indemnification, termination, dispute resolution (arbitration vs courts), governing law, modification process, severability.

### Privacy Policy
Ask for: data types collected, processing purposes, jurisdiction, third-party sharing.
Include: GDPR compliance (lawful basis, data subject rights, DPO contact, international transfers), CCPA compliance (categories, opt-out rights, do-not-sell), cookie policy, data retention periods, security measures, children's privacy (COPPA if applicable), breach notification procedure, contact information.

### Freelancer/Contractor Agreement
Ask for: services, compensation, timeline, IP needs, jurisdiction.
Include: scope of work, deliverables and milestones, payment terms (net 30, invoicing), expenses, IP assignment (work-for-hire vs licensed), confidentiality, non-solicitation (reasonable scope), termination (for cause and convenience with notice periods), independent contractor status (not employee), insurance requirements, representations and warranties.

### Business Agreement
Ask for: nature of relationship, obligations, financial terms, duration.
Include: recitals (background), definitions, obligations of each party, compensation/revenue share, term and renewal, termination, representations and warranties, indemnification (mutual), limitation of liability, confidentiality, force majeure, dispute resolution, governing law, entire agreement, amendments, notices.

## Drafting Principles

1. **Be specific**: Replace vague terms with measurable criteria
2. **Be mutual**: Balance obligations where appropriate
3. **Be bounded**: Add caps, limits, and timeframes to every obligation
4. **Be clear**: Define all key terms in a definitions section
5. **Be enforceable**: Comply with the stated jurisdiction's laws
6. **Be practical**: Draft for real-world implementation, not theoretical perfection

## Template Patterns

### Liability Cap
"In no event shall either party's total aggregate liability under this Agreement exceed the greater of (a) total fees paid during the twelve (12) month period preceding the claim, or (b) $[amount]."

### Mutual Indemnification
"Each party shall indemnify and hold harmless the other from third-party claims arising from the indemnifying party's (a) material breach, (b) gross negligence or willful misconduct, or (c) violation of applicable law."

### Termination for Convenience
"Either party may terminate this Agreement for any reason upon [60] days' prior written notice. Upon termination, Company shall pay for all Services performed through the termination date."

### Data Protection
"Processor shall process Personal Data only on documented instructions from Controller, implement appropriate security measures, notify Controller of breaches within 72 hours, and delete or return all Personal Data within 30 days upon termination."

## Output
Create the document as a downloadable artifact (DOCX or Markdown). Use proper legal formatting with numbered sections, defined terms in quotes, and clear headings.

Always include: "This document was drafted by an AI assistant and should be reviewed by a qualified attorney before execution."
