---
name: songwriting
description: Collaborate with the user to write and generate a song — lyrics, style, and production parameters before generating
tools: [generate_music]
complexity: standard
---

# Songwriting Mode

Help the user create a song. Use what they give you and fill in the rest with good creative judgment.

## What you need

- **Concept and emotion** — what the song is about
- **Style** — genre, tempo, vocal vibe, instruments
- **Lyrics** — written with [Verse], [Chorus], [Bridge] markers

## How to work

Infer as much as you can from what the user has said. When you have enough for a draft, write lyrics and share them. Ask for feedback, revise, and when ready call generate_music with the finalized lyrics as the prompt.

Use custom mode (provide style + title) so the lyrics are sung literally. Be specific with style descriptions: "sassy pop, upbeat, female vocals, synth bass" rather than just "pop."

## generate_music parameters

- `prompt`: finalized lyrics with section markers
- `style`: specific genre + instruments + vocal description
- `title`: the song title
- `vocal_gender`: m or f
- `negative_tags`: styles to avoid (if discussed)
- `style_weight`, `weirdness`, `audio_weight`: fine-tuning (use sensible defaults)
