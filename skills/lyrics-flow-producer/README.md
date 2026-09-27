# Lyrics Flow Producer (`lyrics-flow-producer`)

A token-minimal, studio-grade AI Lyric Video Producer Skill built on top of [`zysilm/video-producer-skill`](https://github.com/zysilm/video-producer-skill) — engineered to turn **pasted song lyrics** into cohesive **Gemini Nano Banana keyframe images** and **Google Flow (`Veo 3.1`) video segments** with an **89% reduction in token usage** (`91` lines vs. the original `859` lines).

---

## ✨ Key Features & Architecture

1. **Deterministic Lyric & Scene Count Intelligence (`scripts/plan_lyrics_pipeline.py`)**:
   - Parses pasted song lyrics across verses (`Pallavi`), choruses (`Anupallavi`), bridges (`Charanam`), and instrumental interludes.
   - Calculates the exact number of **unique Nano Banana keyframe images** and **8-second Google Flow (`Veo 3.1`) video segments** needed.
   - Replaces 4 redundant markdown/JSON planning files (`philosophy.md`, `style.json`, `scene-breakdown.md`, `pipeline.json`) with a **single unified `output/<project>/pipeline.json`**.
2. **Master Style & Subject Anchor Chaining (Gemini Nano Banana)**:
   - Generates `scene-01-start.png` first using the 6-part Nano Banana prompt formula (`[Subject] + [Pose/Emotion] + [Environment] + [Style] + [Shot/Lens] + [Constraints]`).
   - Passes `scene-01-start.png` as the visual anchor to subsequent scenes so character identity, lighting direction, and color palette stay 100% locked.
3. **Subagent-Isolated Google Flow (`Veo 3.1`) Video Generation**:
   - Spawns isolated subagents (`references/flow-browser-runbook.md`) to drive `https://labs.google/fx/flow` in **Frames to Video (`Video aus Frames`)** mode (`Veo 3.1 - Quality`) without polluting the main conversation with browser snapshots.
   - Chains multi-segment scenes (`> 8s`) seamlessly by extracting the final frame of each segment via `scripts/flow_video_engine.py extract-frame`.
4. **Zero-Token FFmpeg Media Engine (`scripts/flow_video_engine.py`)**:
   - Tracks asset/keyframe/segment completion status (`status`), moves downloaded browser files (`move-download`), extracts continuity frames (`extract-frame`), synthesizes 1080p@30fps camera-motion fallback clips when needed, applies cross-scene transitions (`cut`, `fade`, `dissolve`), muxes local audio (`-14 LUFS`), and exports `output/<project>/output.mp4` (`assemble`).

---

## 📂 Repository Structure

```text
lyrics-flow-producer/
├── SKILL.md                                 # Main 5-Phase Agent Skill instruction file (91 lines)
├── README.md                                # Documentation & quickstart guide
├── LICENSE                                  # MIT License
├── references/
│   ├── prompt-formulas.md                   # Nano Banana 6-part & Veo 3.1 5-part prompt formulas
│   └── flow-browser-runbook.md              # Subagent browser runbook for labs.google/fx/flow
└── scripts/
    ├── plan_lyrics_pipeline.py              # Lyric parser, image/segment counter & pipeline scaffolder
    └── flow_video_engine.py                 # Frame extractor, status syncer & FFmpeg video assembler
```

---

## 🚀 Installation & Usage

### Install into Your Workspace Skills Directory
```bash
git clone https://github.com/vamshicreates/lyrics-flow-producer.git .agents/skills/lyrics-flow-producer
```

### 1. Scaffold Pipeline & Calculate Image/Video Counts from Lyrics
```bash
python3 .agents/skills/lyrics-flow-producer/scripts/plan_lyrics_pipeline.py \
  --project "my-song" \
  --lyrics-file lyrics.txt
```

### 2. Check Pipeline Status
```bash
python3 .agents/skills/lyrics-flow-producer/scripts/flow_video_engine.py status \
  --pipeline output/my-song/pipeline.json
```

### 3. Extract Last Frame for Multi-Segment Flow Chaining
```bash
python3 .agents/skills/lyrics-flow-producer/scripts/flow_video_engine.py extract-frame \
  --video output/my-song/scene-01/seg-A.mp4 \
  -o output/my-song/scene-01/extracted/after-seg-A.png
```

### 4. Assemble Final Master Video (`output.mp4`)
```bash
python3 .agents/skills/lyrics-flow-producer/scripts/flow_video_engine.py assemble \
  --pipeline output/my-song/pipeline.json \
  -o output/my-song/output.mp4
```

---

## 🙏 Acknowledgments
Built on top of the Production Philosophy and Scene/Segment Chaining concepts from [`zysilm/video-producer-skill`](https://github.com/zysilm/video-producer-skill).
