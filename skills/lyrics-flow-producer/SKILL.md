---
name: lyrics-flow-producer
description: >-
  Token-minimal, studio-grade AI Lyric Video Producer built on top of zysilm/video-producer-skill.
  Trigger whenever the user pastes song lyrics and wants relevant images and AI video clips
  generated using Gemini Nano Banana and Google Flow (Veo 3.1). Understands the lyrics deeply,
  calculates the exact number of relevant keyframe images and 8-second Flow video segments needed,
  locks visual style via a unified Production Philosophy (`pipeline.json`), generates consistent
  Nano Banana keyframes, chains 8-second Veo 3.1 video segments via Google Flow browser subagents,
  and concatenates the final master MP4.
---

# Lyrics Flow Producer (`lyrics-flow-producer`)

Turn pasted song lyrics into a cohesive, continuous-shot or multi-scene AI music video using **Gemini Nano Banana** (for keyframes/assets) and **Google Flow / Veo 3.1** (for 8-second frame-anchored video generation), built on the architecture of `zysilm/video-producer-skill` with **80% fewer tokens**.

---

## Token-Efficiency Rules (Mandatory)
1. **Single Unified Plan (`pipeline.json`)**: Do NOT create separate `philosophy.md`, `style.json`, and `scene-breakdown.md` files. Store the Production Philosophy, Lyric Meaning, Keyframe Prompts, and Veo Motion Prompts inside a single `output/<project>/pipeline.json`.
2. **CLI-First Math & Media**: Always run [plan_lyrics_pipeline.py](./scripts/plan_lyrics_pipeline.py) and [flow_video_engine.py](./scripts/flow_video_engine.py) instead of writing ad-hoc Python/FFmpeg one-liners.
3. **Subagent Context Isolation**: Never run multi-step Google Flow browser loops in the main conversation. Spawn isolated subagents (`invoke_subagent`) that read [flow-browser-runbook.md](./references/flow-browser-runbook.md) and return only a 1-line JSON result.

---

## 5-Phase Execution Workflow

### Phase 1: Understand Lyrics & Calculate Exact Image / Video Counts
1. Run the deterministic lyric analyzer to scaffold `output/<project>/pipeline.json`:
   ```bash
   python3 .agents/skills/lyrics-flow-producer/scripts/plan_lyrics_pipeline.py \
     --project "<song-slug>" \
     --lyrics "<pasted-lyrics>"
   ```
2. Read [prompt-formulas.md](./references/prompt-formulas.md) and populate the `<FILL_...>` fields in `output/<project>/pipeline.json`:
   - `philosophy`: Lock `art_style`, `color_palette`, `lighting`, `main_subject`, and `environment`.
   - For each scene in `scenes[]`:
     - Translate the lyric couplet's **deep meaning & emotional arc** into `meaning` and `emotion`.
     - Write `first_keyframe.prompt` (60–100 words, Nano Banana 6-part formula: `[Subject] + [Pose/Emotion] + [Environment] + [Style] + [Shot/Lens] + [No text/watermark]`).
     - Write each segment's `motion_prompt` (100–140 words, Veo 3.1 5-part formula: `[Cinematography] + [Subject] + [ONE Primary Action] + [Context] + [Style & Ambiance]`).
3. Present a concise **Production Plan Table** in chat showing:
   - **Total Relevant Images Needed**: `unique_keyframes_needed` (reusing chorus keyframes where appropriate or creating new camera angles)
   - **Total 8s Flow Video Segments**: `total_veo_video_segments`
   - Scene-by-scene breakdown (`Scene # | Lyric Lines | Meaning | Keyframe Visual | Veo Motion`).

---

### Phase 2: Generate Relevant Keyframe Images (Gemini Nano Banana)
Generate every scene's starting keyframe (`output/<project>/keyframes/scene-XX-start.png`):
1. **Primary Zero-Config Method — Built-in `generate_image` (Nano Banana)**:
   - Generate `scene-01-start.png` first to establish the **Master Visual Anchor**.
   - For `scene-02` through `scene-NN`, pass `ImagePaths=["<abs_path_to_scene_01_start.png>"]` in `generate_image` so character features, outfits, color grade, and lighting stay 100% locked across all scenes.
   - Copy each generated artifact image to `output/<project>/keyframes/scene-XX-start.png`.
2. **Alternative — Google Flow UI ("Text to Image" / Nano Banana Pro)**:
   - If the user prefers generating images inside `https://labs.google/fx/flow`, spawn `invoke_subagent` following [flow-browser-runbook.md](./references/flow-browser-runbook.md).
3. Sync status in `pipeline.json`:
   ```bash
   python3 .agents/skills/lyrics-flow-producer/scripts/flow_video_engine.py status --pipeline output/<project>/pipeline.json
   ```

---

### Phase 3: Generate Video Segments in Google Flow (Veo 3.1 Quality)
For each scene's segments in `pipeline.json`:
1. **Subagent Execution on Google Flow (`https://labs.google/fx/flow`)**:
   - Spawn `invoke_subagent` (`TypeName: "self"`, `Role: "Flow Segment Generator"`) with instructions to follow [flow-browser-runbook.md](./references/flow-browser-runbook.md):
     - Select **"Frames to Video" (`Video aus Frames`)** mode with **Veo 3.1 - Quality**, `1` output, matching aspect ratio.
     - Upload `start_frame` (`keyframes/scene-XX-start.png`, or `extracted/after-seg-A.png` for chained segments >8s).
     - Enter the segment's `motion_prompt`, generate, download the MP4 to `output/<project>/scene-XX/seg-A.mp4`, and extract the end frame if `extract_end_frame: true`.
   - **Parallelism**: Independent scenes (`scene-01`, `scene-02`) can be generated concurrently; segments within the same multi-segment scene (`seg-A` → `seg-B`) MUST run sequentially for frame-chaining continuity.
2. **Local Motion Fallback**:
   - If Google Flow credits are exhausted or the user wants an immediate local render from the Nano Banana keyframes, `flow_video_engine.py assemble` automatically synthesizes smooth 1080p@30fps camera-motion clips (`zoom_in`, `pan_right`, `zoom_out`, `pan_left`) for any segment whose `.mp4` is not yet generated.

---

### Phase 4: Final Concatenation & Audio Mastering
Run the deterministic assembly engine to merge segments within each scene, apply cross-scene transitions (`cut`, `fade`, `dissolve`), mux local song audio (`-14 LUFS`, if an audio file is present in the folder), and export `output/<project>/output.mp4`:
```bash
python3 .agents/skills/lyrics-flow-producer/scripts/flow_video_engine.py assemble \
  --pipeline output/<project>/pipeline.json \
  -o output/<project>/output.mp4
```

---

### Phase 5: Deliver Output
Share clickable links to:
- Final Master Video: `output/<project>/output.mp4`
- Generated Nano Banana Keyframes: `output/<project>/keyframes/`
- Unified Pipeline Manifest: `output/<project>/pipeline.json`
*(If the user also wants synchronized burned-in Unicode/Indic subtitles on top of the final video, chain with `lyrics-to-video` / `video-use`.)*
