#!/usr/bin/env python3
"""Deterministic Lyric Analyzer & Pipeline Scaffolder (built on zysilm/video-producer-skill).

Analyzes pasted song lyrics (and optional local audio), determines the exact number of
relevant Nano Banana keyframes and 8-second Google Flow (Veo 3.1) video segments needed,
and scaffolds a unified `output/<project>/pipeline.json`.

Usage:
    python3 scripts/plan_lyrics_pipeline.py --project "my-song" --lyrics-file lyrics.txt
    python3 scripts/plan_lyrics_pipeline.py --project "my-song" --lyrics "Line 1\nLine 2..."
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
SECTION_RE = re.compile(
    r"^\s*(?:\[([^\]]+)\]|\(([^)]+)\)|"
    r"(pallavi|anupallavi|charanam\s*\d*|verse\s*\d*|chorus|pre-chorus|bridge|intro|outro|interlude|bgm|music))"
    r"\s*:?\s*$",
    re.IGNORECASE,
)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "lyric-video"


def find_audio(search_dir: Path) -> Path | None:
    for d in (search_dir, Path.cwd()):
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                return f.resolve()
    return None


def probe_audio_duration(audio_path: Path) -> float | None:
    try:
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
        return round(float(out.stdout.strip()), 2)
    except Exception:
        return None


def parse_lyrics_into_scenes(raw_lyrics: str, lines_per_scene: int = 2) -> list[dict]:
    """Group lyrics into visual scenes (typically 2 lyric lines = 1 visual scene / 8s segment)."""
    if "\\n" in raw_lyrics and "\n" not in raw_lyrics.strip():
        raw_lyrics = raw_lyrics.replace("\\n", "\n")
    raw_lines = [ln.strip() for ln in raw_lyrics.strip().splitlines()]
    stanzas: list[tuple[str, list[str]]] = []
    curr_section = "VERSE_1"
    curr_lines: list[str] = []
    verse_idx = 1

    for ln in raw_lines:
        if not ln:
            if curr_lines:
                stanzas.append((curr_section, curr_lines))
                curr_lines = []
                verse_idx += 1
                curr_section = f"SECTION_{verse_idx}"
            continue

        m = SECTION_RE.match(ln)
        if m:
            if curr_lines:
                stanzas.append((curr_section, curr_lines))
                curr_lines = []
            label = (m.group(1) or m.group(2) or m.group(3) or "SECTION").upper()
            curr_section = re.sub(r"\s+", "_", label)
            if any(k in curr_section for k in ("MUSIC", "BGM", "INTERLUDE", "INTRO", "OUTRO")):
                stanzas.append((curr_section, []))
                verse_idx += 1
                curr_section = f"SECTION_{verse_idx}"
            continue

        curr_lines.append(ln)

    if curr_lines:
        stanzas.append((curr_section, curr_lines))

    scenes: list[dict] = []
    seen_couplets: dict[str, str] = {}
    scene_num = 1

    for section_name, lines in stanzas:
        # Pure instrumental section
        if not lines:
            sid = f"scene-{scene_num:02d}"
            scenes.append(
                {
                    "id": sid,
                    "section": section_name,
                    "type": "INSTRUMENTAL",
                    "lyric_lines": [],
                    "lyric_text": "",
                    "is_repeat_of": None,
                    "duration_target": 8,
                    "segments_needed": 1,
                }
            )
            scene_num += 1
            continue

        # Chunk stanza lines into visual beats of `lines_per_scene` (default 2 lines per 8s scene)
        for i in range(0, len(lines), lines_per_scene):
            chunk = lines[i : i + lines_per_scene]
            text_joined = " / ".join(chunk)
            norm_key = re.sub(r"\s+", " ", text_joined.lower()).strip()
            repeat_of = seen_couplets.get(norm_key)

            sid = f"scene-{scene_num:02d}"
            if not repeat_of:
                seen_couplets[norm_key] = sid

            # Estimate 4 seconds per sung line (2 lines = 8s = 1 Veo segment; >2 lines = ceil(dur/8))
            est_dur = max(6, min(16, len(chunk) * 4))
            seg_count = max(1, (est_dur + 7) // 8)

            scenes.append(
                {
                    "id": sid,
                    "section": section_name,
                    "type": "VOCAL",
                    "lyric_lines": chunk,
                    "lyric_text": "\n".join(chunk),
                    "is_repeat_of": repeat_of,
                    "duration_target": seg_count * 8,
                    "segments_needed": seg_count,
                }
            )
            scene_num += 1

    return scenes


def build_pipeline(
    project_name: str,
    raw_lyrics: str,
    output_dir: Path,
    audio_path: Path | None = None,
    aspect_ratio: str = "16:9",
    lines_per_scene: int = 2,
) -> dict:
    parsed_scenes = parse_lyrics_into_scenes(raw_lyrics, lines_per_scene=lines_per_scene)
    audio_dur = probe_audio_duration(audio_path) if audio_path else None

    # If audio is longer than sum of vocal scenes, add Intro/Interlude/Outro scenes automatically
    vocal_dur = sum(s["duration_target"] for s in parsed_scenes)
    if audio_dur and audio_dur > vocal_dur + 6:
        extra_time = audio_dur - vocal_dur
        extra_segments = max(1, round(extra_time / 8))
        # Add an intro if not present
        if not parsed_scenes or parsed_scenes[0]["type"] != "INSTRUMENTAL":
            parsed_scenes.insert(
                0,
                {
                    "id": "scene-00",
                    "section": "MUSIC_INTRO",
                    "type": "INSTRUMENTAL",
                    "lyric_lines": [],
                    "lyric_text": "",
                    "is_repeat_of": None,
                    "duration_target": 8,
                    "segments_needed": 1,
                },
            )
            extra_segments -= 1
        if extra_segments > 0:
            parsed_scenes.append(
                {
                    "id": "scene-outro",
                    "section": "MUSIC_OUTRO",
                    "type": "INSTRUMENTAL",
                    "lyric_lines": [],
                    "lyric_text": "",
                    "is_repeat_of": None,
                    "duration_target": min(16, extra_segments * 8),
                    "segments_needed": min(2, extra_segments),
                }
            )
        # Re-index scene IDs cleanly
        for idx, s in enumerate(parsed_scenes, start=1):
            s["id"] = f"scene-{idx:02d}"

    unique_keyframes = sum(1 for s in parsed_scenes if not s.get("is_repeat_of"))
    total_keyframes = len(parsed_scenes)
    total_segments = sum(s["segments_needed"] for s in parsed_scenes)

    pipeline_scenes: list[dict] = []
    cursor_time = 0.0
    for idx, s in enumerate(parsed_scenes):
        sid = s["id"]
        dur = float(s["duration_target"])
        seg_count = s["segments_needed"]
        is_last_scene = idx == len(parsed_scenes) - 1

        segments = []
        for seg_idx in range(seg_count):
            letter = chr(ord("A") + seg_idx)
            seg_id = f"seg-{sid.split('-')[1]}-{letter}"
            segments.append(
                {
                    "id": seg_id,
                    "duration": 8,
                    "start_frame": (
                        f"keyframes/{sid}-start.png"
                        if seg_idx == 0
                        else f"{sid}/extracted/after-seg-{chr(ord('A') + seg_idx - 1)}.png"
                    ),
                    "extract_end_frame": seg_idx < seg_count - 1,
                    "end_frame_path": (
                        f"{sid}/extracted/after-seg-{letter}.png"
                        if seg_idx < seg_count - 1
                        else None
                    ),
                    "motion_prompt": "<FILL_100_WORD_VEO_MOTION_PROMPT: [Cinematography] + [Subject] + [ONE Primary Action] + [Context] + [Style & Ambiance]>",
                    "output_video": f"{sid}/seg-{letter}.mp4",
                    "status": "pending",
                }
            )

        pipeline_scenes.append(
            {
                "id": sid,
                "section": s["section"],
                "type": s["type"],
                "lyric_lines": s["lyric_lines"],
                "lyric": s["lyric_text"],
                "meaning": "<FILL_LYRIC_MEANING_AND_EMOTIONAL_BEAT>",
                "emotion": "<FILL_EMOTION_TAG>",
                "start_s": round(cursor_time, 2),
                "end_s": round(cursor_time + dur, 2),
                "duration_target": int(dur),
                "transition_to_next": None if is_last_scene else ("dissolve" if s["type"] == "INSTRUMENTAL" else "cut"),
                "reuse_keyframe_from": s["is_repeat_of"],
                "first_keyframe": {
                    "prompt": "<FILL_NANO_BANANA_IMAGE_PROMPT: [Subject] + [Pose/Emotion] + [Environment] + [Style] + [Shot/Lens] + [Constraints: no text/watermark]>",
                    "output": f"keyframes/{sid}-start.png",
                    "status": "pending",
                },
                "segments": segments,
            }
        )
        cursor_time += dur

    pipeline = {
        "version": "4.0-lyrics-flow",
        "project_name": project_name,
        "config": {
            "segment_duration": 8,
            "aspect_ratio": aspect_ratio,
            "image_model": "Nano Banana Pro (generate_image / Flow Text-to-Image)",
            "video_model": "Veo 3.1 - Quality (Flow Video from Frames)",
            "outputs_per_prompt": 1,
            "audio_path": str(audio_path) if audio_path else None,
            "audio_duration_s": audio_dur,
        },
        "summary_counts": {
            "total_scenes": len(pipeline_scenes),
            "vocal_scenes": sum(1 for s in pipeline_scenes if s["type"] == "VOCAL"),
            "instrumental_scenes": sum(1 for s in pipeline_scenes if s["type"] == "INSTRUMENTAL"),
            "unique_keyframes_needed": unique_keyframes,
            "total_keyframes_needed": total_keyframes,
            "total_veo_video_segments": total_segments,
            "estimated_total_duration_s": int(cursor_time),
        },
        "philosophy": {
            "visual_style": {
                "art_style": "<FILL_ART_STYLE>",
                "color_palette": "<FILL_PRIMARY_SECONDARY_ACCENT_COLORS>",
                "lighting": "<FILL_LIGHTING_PHILOSOPHY>",
                "composition": "<FILL_SHOT_COMPOSITION_RULES>",
            },
            "motion_language": {
                "movement_quality": "Smooth, deliberate, emotionally weighted",
                "pacing": "Synced to vocal phrasing; atmospheric breathing room on interludes",
                "camera_style": "Slow dolly push-ins, gentle tracking, orbital reveals",
            },
            "subject_consistency": {
                "main_subject": "<FILL_RECURRING_CHARACTER_OR_SUBJECT_DESCRIPTION>",
                "environment": "<FILL_WORLD_AND_SETTING_ANCHOR>",
            },
            "constraints": {
                "avoid": ["text", "watermarks", "logos", "modern anachronisms", "jerky camera"],
                "maintain": ["character facial/outfit consistency", "lighting direction", "color grade"],
            },
        },
        "assets": {
            "characters": {},
            "backgrounds": {},
        },
        "scenes": pipeline_scenes,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("assets/characters", "assets/backgrounds", "keyframes"):
        (output_dir / sub).mkdir(parents=True, exist_ok=True)
    for sc in pipeline_scenes:
        (output_dir / sc["id"] / "extracted").mkdir(parents=True, exist_ok=True)

    pipeline_file = output_dir / "pipeline.json"
    pipeline_file.write_text(json.dumps(pipeline, indent=2, ensure_ascii=False), encoding="utf-8")
    return pipeline


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze lyrics and scaffold Flow pipeline.json")
    ap.add_argument("--project", required=True, help="Project name or slug")
    ap.add_argument("--lyrics", default=None, help="Raw lyrics string")
    ap.add_argument("--lyrics-file", type=Path, default=None, help="Path to text file with lyrics")
    ap.add_argument("--audio", type=Path, default=None, help="Optional path to audio file")
    ap.add_argument("--output-dir", type=Path, default=None, help="Output directory (default: output/<slug>)")
    ap.add_argument("--aspect-ratio", default="16:9", choices=["16:9", "9:16", "1:1"])
    ap.add_argument("--lines-per-scene", type=int, default=2, help="Lyric lines per 8s visual scene (default: 2)")
    args = ap.parse_args()

    raw_lyrics = args.lyrics
    if args.lyrics_file and args.lyrics_file.exists():
        raw_lyrics = args.lyrics_file.read_text(encoding="utf-8")
    if not raw_lyrics or not raw_lyrics.strip():
        sys.exit("Error: Provide --lyrics or --lyrics-file with non-empty song lyrics.")

    slug = slugify(args.project)
    out_dir = (args.output_dir or (Path("output") / slug)).resolve()
    audio_path = args.audio.resolve() if args.audio and args.audio.exists() else find_audio(out_dir)

    pipeline = build_pipeline(
        project_name=slug,
        raw_lyrics=raw_lyrics,
        output_dir=out_dir,
        audio_path=audio_path,
        aspect_ratio=args.aspect_ratio,
        lines_per_scene=args.lines_per_scene,
    )

    c = pipeline["summary_counts"]
    print(
        json.dumps(
            {
                "status": "scaffolded",
                "pipeline_path": str(out_dir / "pipeline.json"),
                "summary_counts": c,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
