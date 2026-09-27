# Nano Banana & Veo 3.1 Prompt Formulas (Token-Compact Reference)

## 1. Lyric-to-Visual Translation Rules
- **Understand Before Prompting**: Never paste raw lyrics into an image/video prompt. Translate each lyric couplet's **literal or metaphorical meaning + emotion** into a concrete cinematic scene.
- **Master Style & Subject Lock**: Every prompt in `pipeline.json` MUST embed the exact `philosophy.subject_consistency` and `philosophy.visual_style` descriptors so characters, outfits, lighting direction, and color grade never drift across scenes.

---

## 2. Nano Banana Image Prompt Formula (Keyframes & Assets)
**Structure (60–100 words):**
```text
[Subject + Outfit + Emotional Expression] + [Pose/Staging] + [Environment/Atmosphere] + [Style & Color Palette] + [Camera Shot & Lens] + [Constraints]
```

- **Constraints (Always Append)**: `"Clean cinematic frame, no text, no subtitles, no watermarks, no logos, consistent lighting from <direction>."`
- **Anchor Chaining (`generate_image` tool)**:
  1. Generate `keyframes/scene-01-start.png` first to establish the visual anchor.
  2. For `scene-02`..`scene-NN`, pass `ImagePaths=[".../keyframes/scene-01-start.png"]` so Gemini Nano Banana preserves character identity and visual style automatically.

---

## 3. Google Flow (Veo 3.1 Quality) Motion Prompt Formula
**Structure (100–140 words, 3–5 sentences):**
```text
[Cinematography: Exact Camera Move + Shot Size] + [Subject Details] + [ONE Primary Physical Action] + [Environment/Context Motion] + [Style, Lighting & Mood]
```

### Mandatory Veo Rules
1. **ONE Primary Action per 8s Segment**: Never list 4+ simultaneous actions. Describe a single fluid trajectory from the start keyframe.
2. **Explicit Camera Verb**: Use `"Slow dolly push-in"`, `"Smooth tracking shot following..."`, `"Gentle crane up"`, `"Slow orbital pan right"`, or `"Static locked-off frame"`. Never write `"camera moves dynamically"`.
3. **Match Start Frame**: The opening state of the motion prompt MUST match what is visible in `start_frame` (`scene-XX-start.png` or `after-seg-X.png`).
4. **Motion Vocabulary**:
   - *Slow/Devotional/Emotional*: `"gradually"`, `"glacially"`, `"gently"`, `"in slow-motion"`, `"softly drifting"`
   - *Energetic/Rhythmic/Anthem*: `"steadily"`, `"fluidly"`, `"sweeping"`, `"pulsing with golden light"`
