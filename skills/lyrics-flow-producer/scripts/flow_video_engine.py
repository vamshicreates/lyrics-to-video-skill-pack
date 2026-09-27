#!/usr/bin/env python3
"""Zero-Token Media Engine for Lyrics-Flow-Producer (built on zysilm/video-producer-skill).

Subcommands:
  1. status        — Sync `pipeline.json` statuses with files on disk and print compact summary.
  2. extract-frame — Extract the exact last frame of a Veo segment MP4 for seamless frame-chaining.
  3. move-download — Move the newest downloaded PNG/MP4 from browser downloads into target path.
  4. assemble      — Merge all segments/scenes (with automatic keyframe motion fallback, cross-scene
                     transitions, and optional audio muxing) into `output/<project>/output.mp4`.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def ensure_ffmpeg_on_path() -> None:
    extra_paths: list[str] = []
    for candidate in sorted(glob.glob("/usr/local/Cellar/ffmpeg/*/bin"), reverse=True):
        extra_paths.append(candidate)
    for candidate in sorted(glob.glob("/opt/homebrew/Cellar/ffmpeg/*/bin"), reverse=True):
        extra_paths.append(candidate)
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = ":".join(extra_paths + [current])


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(out.stdout.strip())


def extract_last_frame(video_path: Path, out_image_path: Path) -> dict:
    if not video_path.exists():
        return {"status": "error", "message": f"Video not found: {video_path}"}
    out_image_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-sseof",
            "-0.15",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out_image_path),
        ],
        check=True,
        capture_output=True,
    )
    return {
        "status": "completed",
        "video": str(video_path),
        "extracted_frame": str(out_image_path),
    }


def move_latest_download(target_path: Path, ext: str | None = None) -> dict:
    search_dirs = [
        Path.cwd() / ".playwright-mcp",
        Path.home() / "Downloads",
    ]
    candidates: list[Path] = []
    target_suffix = (ext or target_path.suffix).lower()
    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file() and f.suffix.lower() == target_suffix and not f.name.startswith("."):
                candidates.append(f)
    if not candidates:
        return {"status": "error", "message": f"No downloaded {target_suffix} found in .playwright-mcp or ~/Downloads"}
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(newest, target_path)
    return {"status": "completed", "source": str(newest), "output": str(target_path)}


def sync_pipeline_status(pipeline_path: Path) -> dict:
    proj_dir = pipeline_path.parent
    data = json.loads(pipeline_path.read_text(encoding="utf-8"))

    assets_done = 0
    assets_total = 0
    for group in ("characters", "backgrounds"):
        for _, item in data.get("assets", {}).get(group, {}).items():
            assets_total += 1
            out_p = proj_dir / item["output"]
            if out_p.exists() and out_p.stat().st_size > 0:
                item["status"] = "completed"
                assets_done += 1

    kf_done = 0
    kf_total = 0
    seg_done = 0
    seg_total = 0

    scene_kf_map: dict[str, Path] = {}
    for sc in data.get("scenes", []):
        kf_total += 1
        kf_rel = sc["first_keyframe"]["output"]
        kf_p = proj_dir / kf_rel
        # Support reusing keyframe from repeated chorus scene if needed
        reuse_id = sc.get("reuse_keyframe_from")
        if not kf_p.exists() and reuse_id and reuse_id in scene_kf_map and scene_kf_map[reuse_id].exists():
            kf_p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(scene_kf_map[reuse_id], kf_p)
        if kf_p.exists() and kf_p.stat().st_size > 0:
            sc["first_keyframe"]["status"] = "completed"
            scene_kf_map[sc["id"]] = kf_p
            kf_done += 1

        for seg in sc.get("segments", []):
            seg_total += 1
            vp = proj_dir / seg["output_video"]
            if vp.exists() and vp.stat().st_size > 0:
                seg["status"] = "completed"
                seg_done += 1
                if seg.get("extract_end_frame") and seg.get("end_frame_path"):
                    efp = proj_dir / seg["end_frame_path"]
                    if not efp.exists():
                        extract_last_frame(vp, efp)

    pipeline_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "project": data.get("project_name"),
        "assets": f"{assets_done}/{assets_total}",
        "keyframes": f"{kf_done}/{kf_total}",
        "segments": f"{seg_done}/{seg_total}",
    }


def render_keyframe_motion_clip(
    image_path: Path,
    out_video: Path,
    duration: float = 8.0,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    motion: str = "zoom_in",
) -> None:
    """Create a smooth 1080p@30fps camera-motion video clip from a keyframe image (fallback when Veo clip is absent)."""
    out_video.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(round(duration * fps)))
    up_w, up_h = width * 2, height * 2

    if motion == "zoom_out":
        z_expr = f"1.14-0.14*(on/{frames})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif motion == "pan_right":
        z_expr = "1.12"
        x_expr = f"(iw-iw/zoom)*(on/{frames})"
        y_expr = "ih/2-(ih/zoom/2)"
    elif motion == "pan_left":
        z_expr = "1.12"
        x_expr = f"(iw-iw/zoom)*(1-on/{frames})"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        z_expr = f"1.0+0.14*(on/{frames})"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"

    vf = (
        f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase,"
        f"crop={up_w}:{up_h},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_path),
            "-vf",
            vf,
            "-t",
            f"{duration:.2f}",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(out_video),
        ],
        check=True,
        capture_output=True,
    )


def normalize_clip(in_video: Path, out_video: Path, width: int, height: int, fps: int, fade_out: bool = False) -> None:
    dur = probe_duration(in_video)
    vf_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        f"fps={fps}",
        "format=yuv420p",
    ]
    if fade_out and dur > 1.0:
        st = max(0.0, dur - 0.45)
        vf_parts.append(f"fade=t=out:st={st:.2f}:d=0.45")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(in_video),
            "-vf",
            ",".join(vf_parts),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            str(out_video),
        ],
        check=True,
        capture_output=True,
    )


def assemble_pipeline(pipeline_path: Path, output_file: Path | None = None) -> dict:
    sync_pipeline_status(pipeline_path)
    proj_dir = pipeline_path.parent
    data = json.loads(pipeline_path.read_text(encoding="utf-8"))

    aspect = data.get("config", {}).get("aspect_ratio", "16:9")
    width, height = (1080, 1920) if aspect == "9:16" else ((1080, 1080) if aspect == "1:1" else (1920, 1080))
    fps = 30
    motions = ["zoom_in", "pan_right", "zoom_out", "pan_left"]

    norm_clips: list[Path] = []
    build_tmp = proj_dir / ".build_tmp"
    build_tmp.mkdir(parents=True, exist_ok=True)

    for sc_idx, sc in enumerate(data.get("scenes", [])):
        sid = sc["id"]
        kf_path = proj_dir / sc["first_keyframe"]["output"]
        transition = sc.get("transition_to_next")
        segs = sc.get("segments", [])

        scene_seg_paths: list[Path] = []
        for seg_idx, seg in enumerate(segs):
            vp = proj_dir / seg["output_video"]
            if not vp.exists() or vp.stat().st_size == 0:
                if not kf_path.exists():
                    raise RuntimeError(f"Missing both segment video ({vp}) and keyframe ({kf_path}) for {sid}")
                render_keyframe_motion_clip(
                    image_path=kf_path,
                    out_video=vp,
                    duration=float(seg.get("duration", 8)),
                    width=width,
                    height=height,
                    fps=fps,
                    motion=motions[(sc_idx + seg_idx) % len(motions)],
                )
            norm_p = build_tmp / f"norm_{sid}_{seg_idx:02d}.mp4"
            is_last_seg_in_scene = seg_idx == len(segs) - 1
            fade_flag = is_last_seg_in_scene and transition in ("fade", "dissolve")
            normalize_clip(vp, norm_p, width, height, fps, fade_out=fade_flag)
            scene_seg_paths.append(norm_p)
            norm_clips.append(norm_p)

        # Save intermediate `scene-XX/scene.mp4` matching zysilm/video-producer-skill structure
        scene_list = build_tmp / f"{sid}_concat.txt"
        scene_list.write_text("\n".join(f"file '{p.resolve()}'" for p in scene_seg_paths) + "\n", encoding="utf-8")
        scene_mp4 = proj_dir / sid / "scene.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(scene_list), "-c", "copy", str(scene_mp4)],
            check=True,
            capture_output=True,
        )

    master_concat = build_tmp / "master_concat.txt"
    master_concat.write_text("\n".join(f"file '{p.resolve()}'" for p in norm_clips) + "\n", encoding="utf-8")

    visual_only = build_tmp / "visual_master.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(master_concat), "-c", "copy", str(visual_only)],
        check=True,
        capture_output=True,
    )

    final_out = (output_file or (proj_dir / "output.mp4")).resolve()
    audio_str = data.get("config", {}).get("audio_path")
    audio_path = Path(audio_str) if audio_str else None

    if audio_path and audio_path.exists():
        vis_dur = probe_duration(visual_only)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(visual_only),
                "-i",
                str(audio_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-af",
                "loudnorm=I=-14:TP=-1.0:LRA=11",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-t",
                f"{vis_dur:.2f}",
                str(final_out),
            ],
            check=True,
            capture_output=True,
        )
    else:
        shutil.copy2(visual_only, final_out)

    shutil.rmtree(build_tmp, ignore_errors=True)
    sync_pipeline_status(pipeline_path)
    return {
        "status": "completed",
        "output_video": str(final_out),
        "duration_s": round(probe_duration(final_out), 2),
        "scenes_merged": len(data.get("scenes", [])),
    }


def main() -> None:
    ensure_ffmpeg_on_path()
    ap = argparse.ArgumentParser(description="Flow Video Engine for Lyrics-Flow-Producer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_stat = sub.add_parser("status", help="Sync and show pipeline status")
    p_stat.add_argument("--pipeline", type=Path, required=True)

    p_ext = sub.add_parser("extract-frame", help="Extract last frame from segment video for chaining")
    p_ext.add_argument("--video", type=Path, required=True)
    p_ext.add_argument("-o", "--out", type=Path, required=True)

    p_mv = sub.add_parser("move-download", help="Move newest downloaded file to target path")
    p_mv.add_argument("-o", "--out", type=Path, required=True)
    p_mv.add_argument("--ext", default=None)

    p_asm = sub.add_parser("assemble", help="Concatenate all segments/scenes into output.mp4")
    p_asm.add_argument("--pipeline", type=Path, required=True)
    p_asm.add_argument("-o", "--output", type=Path, default=None)

    args = ap.parse_args()
    if args.cmd == "status":
        print(json.dumps(sync_pipeline_status(args.pipeline.resolve()), indent=2))
    elif args.cmd == "extract-frame":
        print(json.dumps(extract_last_frame(args.video.resolve(), args.out.resolve()), indent=2))
    elif args.cmd == "move-download":
        print(json.dumps(move_latest_download(args.out.resolve(), args.ext), indent=2))
    elif args.cmd == "assemble":
        out = args.output.resolve() if args.output else None
        print(json.dumps(assemble_pipeline(args.pipeline.resolve(), out), indent=2))


if __name__ == "__main__":
    main()
