# Lyrics-to-Video Skill Pack (`lyrics-to-video-skill-pack`)

A complete, self-contained AI Agent Skill Pack that turns **song lyrics pasted in chat + a local song audio file** into a finished, cinema-grade illustrated lyric video (`1920x1080 @ 30fps`).

## Included Skills

This folder bundles all required skills so you can copy it to any machine or push it directly to GitHub:

1. **[`skills/lyrics-to-video`](./skills/lyrics-to-video/SKILL.md)** — Main end-to-end orchestrator:
   - Auto-discovers the local song audio file (`.mp3`, `.wav`, `.m4a`, `.flac`) in your project/workspace folder.
   - Transcribes the song at word-level granularity and maps exact vocal timestamps vs. instrumental music interludes (`scripts/align_audio_and_music.py`).
   - Understands every lyric line and writes **Master Style Anchor** prompts for consistent image generation across the entire song.
   - Displays lyrics on screen **strictly when they are sung** (`[lyric_start, lyric_end]`).
   - Automatically cuts across **2–3 different images during every instrumental/music-only interlude** with no text on screen so the video moves dynamically with the music.
   - Renders native Indic/Telugu/Hindi/Tamil/Unicode typography via macOS CoreText + Pillow and exports the final MP4 locally (`scripts/build_slideshow.py`).
2. **[`skills/video-use`](./skills/video-use/SKILL.md)** — Companion video editing, color grading (`grade.py`), ElevenLabs Scribe ASR (`transcribe.py`, `pack_transcripts.py`), EDL rendering (`render.py`), and timeline QC (`timeline_view.py`) skill.

---

## Quick Install (Any Machine or Workspace)

Clone or copy `lyrics-to-video-skill-pack` and run:

```bash
chmod +x install.sh
./install.sh /path/to/your/workspace
```

*(If you omit the path argument, `./install.sh` installs into the current directory's `.agents/skills/` folder.)*

### Prerequisites
- **macOS or Linux** with `python3` and `ffmpeg` (`install.sh` will auto-install `ffmpeg` via Homebrew if missing).
- **`ELEVENLABS_API_KEY`**: Add your ElevenLabs API key to `.agents/skills/video-use/.env` (used by Scribe to align lyrics and detect instrumental music interludes to the millisecond).

---

## Pushing to GitHub

This folder is pre-configured with a `.gitignore` that excludes `.env` keys, `.venv/`, and heavy `.mp4` outputs:

```bash
cd lyrics-to-video-skill-pack
git init
git add .
git commit -m "Add lyrics-to-video and video-use skill pack"
git branch -M main
git remote add origin https://github.com/<your-username>/lyrics-to-video-skill-pack.git
git push -u origin main
```
