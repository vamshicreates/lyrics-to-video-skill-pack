#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Lyrics-to-Video Skill Pack Installer (bundles `lyrics-to-video` + `video-use`)
# Supports: Google Antigravity (.agents/skills), Claude Code (~/.claude/skills),
#           Codex (~/.codex/skills), and Global Antigravity (~/.gemini/config/skills)
# ==============================================================================

PACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_WORKSPACE="${1:-$(pwd)}"
SKILLS_DEST="$TARGET_WORKSPACE/.agents/skills"

echo "==> Installing Lyrics-to-Video Skill Pack into: $SKILLS_DEST"
mkdir -p "$SKILLS_DEST"

cp -R "$PACK_DIR/skills/lyrics-to-video" "$SKILLS_DEST/"
cp -R "$PACK_DIR/skills/video-use" "$SKILLS_DEST/"
chmod +x "$SKILLS_DEST/lyrics-to-video/scripts/"*.py

# 1. Check / install ffmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "==> ffmpeg not found on PATH. Attempting install via Homebrew (if on macOS)..."
  if command -v brew >/dev/null 2>&1; then
    brew install ffmpeg
  else
    echo "WARNING: Please install ffmpeg manually (e.g., brew install ffmpeg or sudo apt install ffmpeg)."
  fi
fi

# 2. Setup Python virtual environment inside video-use/.venv
VIDEO_USE_DIR="$SKILLS_DEST/video-use"
echo "==> Setting up Python environment in $VIDEO_USE_DIR/.venv ..."
if command -v uv >/dev/null 2>&1; then
  (cd "$VIDEO_USE_DIR" && uv sync)
else
  python3 -m venv "$VIDEO_USE_DIR/.venv"
  "$VIDEO_USE_DIR/.venv/bin/pip" install --upgrade pip
  "$VIDEO_USE_DIR/.venv/bin/pip" install -e "$VIDEO_USE_DIR"
fi

# Link ffmpeg & ffprobe into .venv/bin if available on system
if command -v ffmpeg >/dev/null 2>&1; then
  ln -sfn "$(command -v ffmpeg)" "$VIDEO_USE_DIR/.venv/bin/ffmpeg"
fi
if command -v ffprobe >/dev/null 2>&1; then
  ln -sfn "$(command -v ffprobe)" "$VIDEO_USE_DIR/.venv/bin/ffprobe"
fi

# 3. Configure .env for ElevenLabs Scribe transcription
if [ ! -f "$VIDEO_USE_DIR/.env" ]; then
  if [ -n "${ELEVENLABS_API_KEY:-}" ]; then
    printf "ELEVENLABS_API_KEY=%s\n" "$ELEVENLABS_API_KEY" > "$VIDEO_USE_DIR/.env"
    chmod 600 "$VIDEO_USE_DIR/.env"
    echo "==> Saved ELEVENLABS_API_KEY from environment to $VIDEO_USE_DIR/.env"
  else
    cp "$VIDEO_USE_DIR/.env.example" "$VIDEO_USE_DIR/.env"
    echo "==> Created $VIDEO_USE_DIR/.env — add your ELEVENLABS_API_KEY there for Scribe audio alignment."
  fi
fi

echo ""
echo "=================================================================="
echo "SUCCESS! Installed skills:"
echo "  1. $SKILLS_DEST/lyrics-to-video"
echo "  2. $SKILLS_DEST/video-use"
echo ""
echo "Usage: Drop your song audio (.mp3/.wav/.m4a) into the workspace"
echo "       folder, paste the song lyrics in chat, and the agent will"
echo "       automatically build the full audio-synced lyric video!"
echo "=================================================================="
