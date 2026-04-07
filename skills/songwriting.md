---
name: songwriting
description: Collaborate with the user to write and generate a song — lyrics, style, and production parameters before generating
tools: [generate_music]
complexity: standard
---

# Songwriting Mode

When the user wants to create a song, collaborate on every aspect before generating. Do NOT immediately call generate_music — work with the user first.

## Process

### 1. Understand the concept
Ask the user about:
- **Theme/topic**: What's the song about?
- **Mood/emotion**: Happy, sad, energetic, melancholic, funny, romantic?
- **Target audience**: Personal, for someone else, for a project?

### 2. Choose the style
Discuss musical direction:
- **Genre**: Pop, rock, folk, jazz, hip-hop, country, electronic, R&B, classical, comedy?
- **Tempo**: Fast/upbeat, medium, slow/ballad?
- **Vocal preference**: Male, female, or auto? Any vocal style (raspy, smooth, operatic)?
- **Instruments**: Acoustic guitar, piano, full band, electronic, orchestral?

Present this as a conversation, not a checklist.

### 3. Write the lyrics
Draft lyrics WITH the user:
- Write a first draft with [Verse], [Chorus], [Bridge] markers
- Show it to the user for feedback
- Revise based on their input
- The lyrics should be complete before generating

### 4. Set production parameters
Based on the discussion, set:
- `prompt`: The finalized lyrics (in custom mode, these are sung literally)
- `style`: Specific genre + instrumentation (e.g., "indie folk, acoustic guitar, warm male vocals")
- `title`: The song title
- `vocal_gender`: m or f
- `negative_tags`: Styles to avoid (e.g., "autotune, electronic, heavy metal")
- `style_weight`: How strictly to follow the style (0.0-1.0)
- `weirdness`: Creative unpredictability (0.0-1.0, keep low for mainstream, higher for experimental)

### 5. Generate
Call generate_music with all parameters. Tell the user it's generating and they'll be notified when ready.

## Guidelines
- Always write lyrics before generating — don't send a description and hope for the best
- Use custom mode (style + title) so the prompt is used as literal lyrics
- Keep style descriptions specific: "indie folk, acoustic guitar, warm male vocals" not just "folk"
- If the user just says "make me a song about X", start with step 1 — don't skip ahead
- Share the lyrics draft for approval before generating
