# Google Flow (`labs.google/fx/flow`) Browser Subagent Runbook

Use this runbook inside isolated subagents (`invoke_subagent`) so browser snapshots never bloat the main conversation context.

## 1. Flow UI Reference (`https://labs.google/fx/flow`)

| Mode | English / German UI Label | Model | Purpose |
|------|---------------------------|-------|---------|
| **Text to Image** | `"Text to Image"` / `"Bild erstellen"` | **Nano Banana Pro** | Generate assets & scene keyframes (if not using built-in `generate_image`) |
| **Frames to Video** | `"Frames to Video"` / `"Video from Frames"` / `"Video aus Frames"` | **Veo 3.1 - Quality** | Generate 8s video segments from `start_frame` |

### Required Flow Video Settings (via `"tune"` / `"Settings"` / `"Einstellungen"` button)
- **Model**: `Veo 3.1 - Quality` (or `Veo 3.1 - Fast` if user requests speed/low credits)
- **Outputs per prompt**: `1`
- **Aspect Ratio**: `16:9` (Landscape / `Querformat 16:9`) or `9:16` (Portrait) matching `pipeline.json`

---

## 2. Subagent Execution Steps for a Video Segment (`segment-generator`)

When spawned to generate segment `seg_id` from `start_frame_path`:
1. **Open/Select Flow Page**:
   - Use `chrome-devtools` (`list_pages` / `navigate_page` to `https://labs.google/fx/flow`) or fallback to the internal browser.
   - Verify user is signed in and inside a Flow project (click `"New project"` / `"Neues Projekt"` if on dashboard).
2. **Select Mode & Settings**:
   - Take snapshot (`take_snapshot`).
   - Switch mode combobox to **`"Frames to Video"` / `"Video from Frames"` / `"Video aus Frames"`**.
   - Confirm settings: `Veo 3.1`, `1` output, `16:9`.
3. **Upload Start Frame**:
   - Click the **`"add"` / `"+"` (Start frame)** button and upload `start_frame_path`.
4. **Submit Motion Prompt**:
   - Fill the prompt textarea with `motion_prompt`.
   - Click **`"Create"` / `"Generate"` / `"Erstellen"`**.
5. **Download & Move Output**:
   - Wait for generation to complete (~45–90s), click the **Download** button on the generated video card.
   - Move the downloaded MP4 into `output_video_path`:
     ```bash
     python3 .agents/skills/lyrics-flow-producer/scripts/flow_video_engine.py move-download -o "<output_video_path>" --ext .mp4
     ```
6. **Extract End Frame (if `extract_end_frame: true`)**:
   ```bash
   python3 .agents/skills/lyrics-flow-producer/scripts/flow_video_engine.py extract-frame --video "<output_video_path>" -o "<end_frame_path>"
   ```
7. **Return Compact JSON Only**:
   Return ONLY:
   ```json
   {"status": "completed", "segment_id": "<id>", "output_video": "<output_video_path>", "end_frame": "<end_frame_path>"}
   ```
