---
name: lyrics-to-video
description: >-
  End-to-end audio-synchronized lyric slideshow video creator. Trigger this skill
  automatically whenever the user pastes or provides song lyrics in the chat (with
  the song audio file already in the project/workspace folder), or asks to turn lyrics
  and a song into an illustrated slideshow / lyric video. Discovers and transcribes the
  local song audio file, understands every lyric line, writes consistent-style image
  generation prompts, synchronizes lyrics strictly to when they are sung on screen,
  inserts 2-3 dynamic image changes during every instrumental/music-only interlude,
  edits the video using the video-use skill, burns lyrics onto the video, and exports
  the final MP4 locally.
---

# Lyrics to Video (`lyrics-to-video`)

Turn song lyrics + a local song audio file into a complete, cinema-grade illustrated lyric video end-to-end — with exact vocal-timed on-screen lyrics and **2–3 dynamic visual image cuts during every instrumental/music interlude**.

---

## Core Workflow (8 Mandatory Steps)

Whenever the user provides lyrics in the chat (and has the song audio file in the folder), execute this end-to-end pipeline:

### 1. Auto-Discover & Transcribe the Song Audio File
1. **Locate the song audio in the folder**:
   - Scan the workspace/project folder (`*.mp3`, `*.wav`, `*.m4a`, `*.flac`, `*.aac`) for the song audio file.
   - Probe its exact duration with `ffprobe`.
2. **Transcribe with `video-use` (`transcribe.py` + `pack_transcripts.py`)**:
   - Run `video-use`'s Scribe transcription helper to get word-level verbatim timestamps and audio event tags (`(music)`, silence gaps, vocal starts/ends):
     ```bash
     .agents/skills/video-use/.venv/bin/python .agents/skills/video-use/helpers/transcribe.py "<audio_path>"
     .agents/skills/video-use/.venv/bin/python .agents/skills/video-use/helpers/pack_transcripts.py --edit-dir <edit_dir>
     ```
3. **Analyze Lyric Windows vs. Instrumental Music Interludes**:
   - Run [align_audio_and_music.py](./scripts/align_audio_and_music.py) on the transcript JSON (or inspect `takes_packed.md` and `transcripts/<audio_stem>.json` directly) to separate the timeline into:
     - **Vocal / Lyric Segments**: Exact `[start, end]` windows where each lyric line is actively sung. Lyrics MUST only appear on screen while they are being sung.
     - **Instrumental / Music-Only Segments (Intro, Interludes/BGM between verses, Outro)**: Any musical passage without singing ($\ge 3.0\text{s}$).
   - **Mandatory Music Interlude Rule**: Whenever there is instrumental music (intro, BGM interlude between Pallavi/Charanam, or outro), **cut across 2–3 different images in between** (each ~2.5s–5.0s long, synced to the musical phrasing) with `"lyric": ""` (no lyrics displayed on screen during pure music).

### 2. Understand Every Lyric & Write Consistent-Style Image Prompts
Never write disconnected prompts. Establish a **Master Style Anchor** first:
1. **Define the `style_anchor`**:
   - Lock in the visual medium, film stock/camera lens, lighting, color palette, and recurring character/deity/world descriptors.
2. **Write prompts for both Vocal Slides AND Instrumental Interlude Slides**:
   - **For Vocal Slides**: Translate the exact meaning, emotion, and metaphor of the sung lyric line into a cinematic scene (`[Master Style Anchor] + [Lyric Scene]`).
   - **For Instrumental / Music Interlude Slides (2–3 images per interlude)**: Write 2–3 complementary visual B-roll / atmospheric montage prompts (`[Master Style Anchor] + [Atmospheric / Instrument / Environment / Detail Shot]`) that visually carry the rhythm and emotion of the music between vocal lines.

### 3. Author the Audio-Synced Storyboard (`storyboard.json` & `master.srt`)
Create `projects/<song_slug>/storyboard.json` following [sample_storyboard.json](./examples/sample_storyboard.json):
- Vocal slides have `"lyric": "<sung lyric text>"` (and optional `"lyric_start"` / `"lyric_end"` if the caption should appear for a sub-window of the slide).
- Instrumental music slides (2–3 cuts per musical interlude) have `"lyric": ""` and `"section": "MUSIC_INTERLUDE"`.

```json
{
  "title": "Song Title",
  "song_slug": "song_title",
  "aspect_ratio": "16:9",
  "resolution": [1920, 1080],
  "fps": 30,
  "grade": "warm_cinematic",
  "audio_path": "song.mp3",
  "style_anchor": "Cinematic 35mm film still, Kodak Vision3 500T...",
  "subtitle_style": {
    "mode": "cinematic_lyric",
    "font_name": "Kohinoor Telugu Bold",
    "font_size": 48,
    "margin_v": 105,
    "uppercase": false,
    "pill_bg": true
  },
  "slides": [
    {
      "id": "slide_01_music_intro_1",
      "section": "MUSIC_INTRO",
      "lyric": "",
      "meaning": "Instrumental intro cut 1 — wide establishing shot",
      "start": 0.0,
      "end": 3.5,
      "motion": "zoom_in",
      "prompt": "...",
      "image_path": "images/slide_01.png"
    },
    {
      "id": "slide_02_music_intro_2",
      "section": "MUSIC_INTRO",
      "lyric": "",
      "meaning": "Instrumental intro cut 2 — atmospheric detail shot",
      "start": 3.5,
      "end": 7.0,
      "motion": "pan_right",
      "prompt": "...",
      "image_path": "images/slide_02.png"
    },
    {
      "id": "slide_03_verse_1",
      "section": "VERSE_1",
      "lyric": "First sung lyric line appears right on vocal entry",
      "lyric_start": 7.0,
      "lyric_end": 12.2,
      "meaning": "Vocal entry — main subject reveal",
      "start": 7.0,
      "end": 12.2,
      "motion": "zoom_in",
      "prompt": "...",
      "image_path": "images/slide_03.png"
    }
  ]
}
```

### 4. Generate All Slide Images (Nano Banana / Google Flow / `generate_image`)
1. **Primary Method — Built-in `generate_image` Tool (Nano Banana)**:
   - Generate `slide_01` first to establish the visual anchor.
   - Pass the anchor image path in `ImagePaths` for subsequent slides so every vocal slide and every instrumental B-roll slide shares the exact same visual style and character consistency.
   - Save all images to `projects/<song_slug>/images/slide_NN.png`.
2. **Alternative Batch API Method (`scripts/generate_images.py`)**:
   - Run `.agents/skills/video-use/.venv/bin/python .agents/skills/lyrics-to-video/scripts/generate_images.py --storyboard projects/<song_slug>/storyboard.json`.

### 5 & 6. Build the Slideshow & Edit with `video-use`
Run [build_slideshow.py](./scripts/build_slideshow.py) to convert the slide images into Ken Burns motion clips, generate `edit/edl.json` and `edit/master.srt`, and execute `video-use/helpers/render.py`:

```bash
.agents/skills/video-use/.venv/bin/python .agents/skills/lyrics-to-video/scripts/build_slideshow.py \
  --storyboard projects/<song_slug>/storyboard.json \
  --output projects/<song_slug>/final_<song_slug>.mp4
```

### 7. Synchronized On-Screen Lyrics + Music Interlude Cuts
- **Vocal Segments**: Lyrics are rendered LAST in the pipeline (`video-use` Hard Rule 1) via native Apple CoreText (supporting Telugu, Hindi, Tamil, Kannada, English, and all Unicode scripts with full conjunct shaping) + `ffmpeg` alpha-fade overlay strictly during `[lyric_start, lyric_end]`.
- **Instrumental / Music Segments**: The 2–3 interlude slides play back-to-back with smooth Ken Burns camera motion (`zoom_in`, `zoom_out`, `pan_left`, `pan_right`) and **zero text overlay**, letting the visuals breathe with the music before the next lyric line enters.
- **Master Audio Mix**: The song audio file is muxed and loudness-normalized (`-14 LUFS`, `-1.0 dBTP`) across the full timeline.

### 8. Verify & Export Final Video Locally
1. Run `video-use/helpers/timeline_view.py` on the rendered video to verify cut pacing during music interludes, lyric alignment on vocal phrases, and color grade consistency.
2. Export the final MP4 to `projects/<song_slug>/final_<song_slug>.mp4` (and `projects/<song_slug>/edit/final.mp4`) and share clickable links with the user.
