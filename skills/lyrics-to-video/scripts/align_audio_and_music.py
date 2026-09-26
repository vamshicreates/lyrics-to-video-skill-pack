#!/usr/bin/env python3
"""Discover local song audio, read Scribe word-level transcript, and map vocal vs. music interludes.

Automatically detects:
  - Exact vocal phrase windows [start, end] where lyrics are sung on screen.
  - Instrumental / music-only windows (intro, interludes >= min_music_gap, outro)
    and splits each musical window into 2-3 dynamic image cuts with empty lyrics.

Usage:
    python scripts/align_audio_and_music.py --project-dir projects/my_song
    python scripts/align_audio_and_music.py --audio "projects/my_song/song.mp3" --out timeline.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
VIDEO_USE_DIR = SKILL_DIR.parent / "video-use"
TRANSCRIBE_PY = VIDEO_USE_DIR / "helpers" / "transcribe.py"
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"]


def ensure_ffmpeg_on_path() -> None:
    extra_paths: list[str] = [str(VIDEO_USE_DIR / ".venv" / "bin")]
    for candidate in sorted(glob.glob("/usr/local/Cellar/ffmpeg/*/bin"), reverse=True):
        extra_paths.append(candidate)
    for candidate in sorted(glob.glob("/opt/homebrew/Cellar/ffmpeg/*/bin"), reverse=True):
        extra_paths.append(candidate)
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = ":".join(extra_paths + [current])


def find_audio_file(search_dir: Path) -> Path | None:
    """Scan search_dir and parent workspace directories for an audio file."""
    dirs_to_check = [search_dir, Path.cwd(), search_dir.parent]
    for d in dirs_to_check:
        if not d.exists():
            continue
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
                return p.resolve()
    return None


def probe_duration(audio_path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def split_music_window(start: float, end: float, label: str, seq_start: int) -> list[dict]:
    """Split an instrumental music window into 2-3 visual cuts with no lyrics."""
    dur = end - start
    if dur < 5.5:
        n_cuts = 2
    else:
        n_cuts = 3

    # For very long intros/outros (>15s), cap each cut at ~4.5s or split into sets of 3
    step = round(dur / n_cuts, 3)
    cuts: list[dict] = []
    curr = start
    for i in range(n_cuts):
        nxt = end if i == n_cuts - 1 else round(curr + step, 3)
        cuts.append(
            {
                "type": "MUSIC_INTERLUDE",
                "section": f"{label}_CUT_{i + 1}_OF_{n_cuts}",
                "start": round(curr, 2),
                "end": round(nxt, 2),
                "duration": round(nxt - curr, 2),
                "lyric": "",
                "motion": MOTIONS[(seq_start + i) % len(MOTIONS)],
                "meaning": f"Instrumental music cut {i + 1}/{n_cuts} ({label}) — visual change on music",
            }
        )
        curr = nxt
    return cuts


def build_vocal_and_music_timeline(
    transcript: dict,
    total_duration: float,
    phrase_silence_gap: float = 0.65,
    min_music_gap: float = 3.0,
) -> list[dict]:
    """Group word timestamps into vocal phrases and insert 2-3 image cuts on music gaps."""
    words = [
        w
        for w in transcript.get("words", [])
        if w.get("type") == "word" and (w.get("text") or "").strip()
    ]
    if not words:
        return split_music_window(0.0, total_duration, "MUSIC_ONLY", 0)

    phrases: list[dict] = []
    curr_words = [words[0]]
    for w in words[1:]:
        gap = float(w["start"]) - float(curr_words[-1]["end"])
        if gap >= phrase_silence_gap:
            phrases.append(
                {
                    "start": float(curr_words[0]["start"]),
                    "end": float(curr_words[-1]["end"]),
                    "heard_text": " ".join(x["text"].strip() for x in curr_words),
                }
            )
            curr_words = [w]
        else:
            curr_words.append(w)
    if curr_words:
        phrases.append(
            {
                "start": float(curr_words[0]["start"]),
                "end": float(curr_words[-1]["end"]),
                "heard_text": " ".join(x["text"].strip() for x in curr_words),
            }
        )

    timeline: list[dict] = []
    cursor = 0.0
    seq = 0

    for idx, p in enumerate(phrases, start=1):
        p_start = max(cursor, round(p["start"] - 0.10, 2))
        p_end = round(p["end"] + 0.15, 2)
        gap = p_start - cursor

        if gap >= min_music_gap:
            label = "MUSIC_INTRO" if cursor == 0.0 else f"MUSIC_INTERLUDE_{idx}"
            music_cuts = split_music_window(cursor, p_start, label, seq)
            timeline.extend(music_cuts)
            seq += len(music_cuts)
            cursor = p_start
        else:
            # Absorb tiny <3.0s breath gap into the vocal slide's visual window,
            # while keeping lyric_start/lyric_end strictly on the sung words!
            p_start = cursor

        timeline.append(
            {
                "type": "VOCAL_LYRIC",
                "section": f"LYRIC_{idx:02d}",
                "start": round(p_start, 2),
                "end": round(p_end, 2),
                "duration": round(p_end - p_start, 2),
                "lyric_start": round(p["start"], 2),
                "lyric_end": round(p["end"], 2),
                "heard_reference": p["heard_text"],
                "lyric": "<REPLACE_WITH_USER_LYRIC_LINE>",
                "motion": MOTIONS[seq % len(MOTIONS)],
            }
        )
        seq += 1
        cursor = p_end

    # Check instrumental outro
    if total_duration - cursor >= min_music_gap:
        outro_cuts = split_music_window(cursor, total_duration, "MUSIC_OUTRO", seq)
        timeline.extend(outro_cuts)
    elif timeline:
        timeline[-1]["end"] = round(total_duration, 2)
        timeline[-1]["duration"] = round(total_duration - timeline[-1]["start"], 2)

    return timeline


def main() -> None:
    ensure_ffmpeg_on_path()
    ap = argparse.ArgumentParser(
        description="Analyze song audio for exact lyric timestamps and 2-3 image cuts on music interludes"
    )
    ap.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project directory")
    ap.add_argument("--audio", type=Path, default=None, help="Explicit path to song audio file")
    ap.add_argument("--min-music-gap", type=float, default=3.0, help="Min seconds for music interlude (2-3 cuts)")
    ap.add_argument("-o", "--out", type=Path, default=None, help="Output JSON timeline path")
    args = ap.parse_args()

    proj_dir = args.project_dir.resolve()
    audio_path = args.audio.resolve() if args.audio else find_audio_file(proj_dir)
    if not audio_path or not audio_path.exists():
        sys.exit(f"No audio file found in {proj_dir}. Place your .mp3/.wav/.m4a song in the folder.")

    edit_dir = proj_dir / "edit"
    tr_path = edit_dir / "transcripts" / f"{audio_path.stem}.json"
    if not tr_path.exists():
        print(f"Transcribing {audio_path.name} via video-use Scribe...")
        subprocess.run(
            [sys.executable, str(TRANSCRIBE_PY), str(audio_path), "--edit-dir", str(edit_dir)],
            check=True,
        )

    total_dur = probe_duration(audio_path)
    transcript = json.loads(tr_path.read_text(encoding="utf-8"))
    timeline = build_vocal_and_music_timeline(
        transcript=transcript,
        total_duration=total_dur,
        min_music_gap=args.min_music_gap,
    )

    out_data = {
        "audio_path": str(audio_path),
        "total_duration_s": round(total_dur, 2),
        "total_segments": len(timeline),
        "vocal_segments": sum(1 for x in timeline if x["type"] == "VOCAL_LYRIC"),
        "music_interlude_cuts": sum(1 for x in timeline if x["type"] == "MUSIC_INTERLUDE"),
        "timeline": timeline,
    }

    out_file = args.out or (edit_dir / "audio_music_timeline.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(out_data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(
        f"Audio: {audio_path.name} ({total_dur:.2f}s)\n"
        f"Mapped {out_data['vocal_segments']} vocal lyric windows + "
        f"{out_data['music_interlude_cuts']} instrumental music cuts (2-3 images per interlude)\n"
        f"Saved timeline -> {out_file}"
    )


if __name__ == "__main__":
    main()
