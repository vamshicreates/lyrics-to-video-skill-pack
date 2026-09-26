#!/usr/bin/env python3
"""Build a complete lyric slideshow video from storyboard.json using video-use.

Pipeline:
  1. Read storyboard.json (lyrics, timings, image paths, motion, grade, style) and auto-discover
     the local song audio file if present in the folder.
  2. Expand any musical interlude slides that specify `music_images` (2-3 images during music)
     and convert each slide image into a motion-polished video clip in sources/slide_NN.mp4
     using native ffmpeg zoompan/crop filters (parallelized across slides).
  3. Generate edit/master.srt (output-timeline lyric captions synced strictly to vocal windows, Rule 5).
  4. Generate edit/edl.json for video-use.
  5. Run video-use/helpers/render.py for per-segment extraction, color grading, and 30ms audio fades.
  6. Render each vocal slide's caption via macOS native CoreText (for flawless Indic/Telugu/Unicode
     shaping) to a transparent PNG and composite LAST (Rule 1) strictly during [lyric_start, lyric_end]
     (leaving instrumental music cuts free of captions), then lossless concat.
  7. Mux and loudness-normalize (-14 LUFS) the local song audio track over the final video.
  8. Write/append session log to edit/project.md and output final MP4.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
import ctypes.util
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from PIL import Image, ImageDraw

SKILL_DIR = Path(__file__).resolve().parent.parent
VIDEO_USE_DIR = SKILL_DIR.parent / "video-use"
VIDEO_USE_RENDER = VIDEO_USE_DIR / "helpers" / "render.py"
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}
DEFAULT_MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left"]


def ensure_ffmpeg_on_path() -> None:
    """Ensure venv bin and Homebrew Cellar ffmpeg bin are at the front of PATH."""
    extra_paths: list[str] = [str(VIDEO_USE_DIR / ".venv" / "bin")]
    for candidate in sorted(glob.glob("/usr/local/Cellar/ffmpeg/*/bin"), reverse=True):
        extra_paths.append(candidate)
    for candidate in sorted(glob.glob("/opt/homebrew/Cellar/ffmpeg/*/bin"), reverse=True):
        extra_paths.append(candidate)
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = ":".join(extra_paths + [current])


def resolve_audio_path(audio_field: str | None, project_dir: Path) -> Path | None:
    """Resolve explicit audio_path or auto-discover an audio file in the project/workspace folder."""
    if audio_field and audio_field != "auto":
        p = Path(audio_field)
        candidates = [p] if p.is_absolute() else [
            (project_dir / p).resolve(),
            (Path.cwd() / p).resolve(),
            (project_dir.parent / p).resolve(),
        ]
        for c in candidates:
            if c.exists():
                return c
    # Auto-discover in project_dir or current working directory
    for d in [project_dir, Path.cwd()]:
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix.lower() in AUDIO_EXTS:
                return f.resolve()
    return None


def expand_slides_for_music_interludes(raw_slides: list[dict]) -> list[dict]:
    """Expand any slide with `music_images` (2-3 images for instrumental sections) into individual cuts."""
    expanded: list[dict] = []
    for idx, s in enumerate(raw_slides, start=1):
        music_imgs = s.get("music_images")
        start = float(s["start"])
        end = float(s["end"])
        lyric = (s.get("lyric") or "").strip()

        # Case 1: Pure music interlude slide with 2-3 images listed in `music_images`
        if not lyric and music_imgs and isinstance(music_imgs, list) and len(music_imgs) >= 2:
            n = len(music_imgs)
            step = (end - start) / n
            curr = start
            for m_idx, img_path in enumerate(music_imgs):
                nxt = end if m_idx == n - 1 else round(curr + step, 3)
                sub = dict(s)
                sub.pop("music_images", None)
                sub["id"] = f"{s.get('id', f'slide_{idx:02d}')}_music_{m_idx + 1}"
                sub["start"] = round(curr, 3)
                sub["end"] = round(nxt, 3)
                sub["image_path"] = img_path
                sub["lyric"] = ""
                sub["motion"] = DEFAULT_MOTIONS[(idx + m_idx) % len(DEFAULT_MOTIONS)]
                expanded.append(sub)
                curr = nxt
            continue

        # Case 2: Vocal slide followed by trailing instrumental music where `lyric_end < end`
        # and `music_images` provides 2-3 images for the trailing music gap
        lyric_end = float(s.get("lyric_end", end))
        if (
            lyric
            and music_imgs
            and isinstance(music_imgs, list)
            and end - lyric_end >= 2.5
        ):
            vocal_slide = dict(s)
            vocal_slide.pop("music_images", None)
            vocal_slide["end"] = round(lyric_end, 3)
            expanded.append(vocal_slide)

            n = len(music_imgs)
            step = (end - lyric_end) / n
            curr = lyric_end
            for m_idx, img_path in enumerate(music_imgs):
                nxt = end if m_idx == n - 1 else round(curr + step, 3)
                sub = {
                    "id": f"{s.get('id', f'slide_{idx:02d}')}_interlude_{m_idx + 1}",
                    "section": "MUSIC_INTERLUDE",
                    "lyric": "",
                    "meaning": f"Instrumental interlude cut {m_idx + 1}/{n}",
                    "start": round(curr, 3),
                    "end": round(nxt, 3),
                    "motion": DEFAULT_MOTIONS[(idx + m_idx) % len(DEFAULT_MOTIONS)],
                    "image_path": img_path,
                }
                expanded.append(sub)
                curr = nxt
            continue

        expanded.append(s)
    return expanded


def srt_timestamp(seconds: float) -> str:
    total_ms = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# -------- Native macOS CoreText shaping for Telugu / Indic / Unicode ---------

class CoreTextRenderer:
    def __init__(self) -> None:
        self.cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        self.cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
        self.ct = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreText"))

        self.cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        self.cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]

        self.ct.CTFontCreateWithName.restype = ctypes.c_void_p
        self.ct.CTFontCreateWithName.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_void_p]

        self.cf.CFDictionaryCreateMutable.restype = ctypes.c_void_p
        self.cf.CFDictionaryCreateMutable.argtypes = [
            ctypes.c_void_p,
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self.cf.CFDictionarySetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

        self.cf.CFAttributedStringCreate.restype = ctypes.c_void_p
        self.cf.CFAttributedStringCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]

        self.ct.CTLineCreateWithAttributedString.restype = ctypes.c_void_p
        self.ct.CTLineCreateWithAttributedString.argtypes = [ctypes.c_void_p]

        self.ct.CTLineGetTypographicBounds.restype = ctypes.c_double
        self.ct.CTLineGetTypographicBounds.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
        ]

        self.cg.CGColorSpaceCreateDeviceRGB.restype = ctypes.c_void_p
        self.cg.CGBitmapContextCreate.restype = ctypes.c_void_p
        self.cg.CGBitmapContextCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        self.cg.CGContextSetRGBFillColor.argtypes = [
            ctypes.c_void_p,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
            ctypes.c_double,
        ]
        self.cg.CGContextSetTextPosition.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
        self.ct.CTLineDraw.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.cg.CGContextRelease.argtypes = [ctypes.c_void_p]
        self.cg.CGColorSpaceRelease.argtypes = [ctypes.c_void_p]

        self.kCFStringEncodingUTF8 = 0x08000100
        self.kCGImageAlphaPremultipliedLast = 1
        self.kCTFontAttributeName = ctypes.c_void_p.in_dll(self.ct, "kCTFontAttributeName")
        self.kCTForegroundColorFromContextAttributeName = ctypes.c_void_p.in_dll(
            self.ct, "kCTForegroundColorFromContextAttributeName"
        )
        self.kCFBooleanTrue = ctypes.c_void_p.in_dll(self.cf, "kCFBooleanTrue")

    def _cfstr(self, s: str) -> int:
        return self.cf.CFStringCreateWithCString(None, s.encode("utf-8"), self.kCFStringEncodingUTF8)

    def render_caption_overlay(
        self,
        text: str,
        width: int,
        height: int,
        font_name: str = "Kohinoor Telugu Bold",
        font_size: int = 48,
        margin_v: int = 105,
        pill_bg: bool = True,
    ) -> Image.Image:
        raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        wrapped_lines: list[str] = []
        for ln in raw_lines:
            if len(ln) > 48:
                wrapped_lines.extend(textwrap.wrap(ln, width=44) or [ln])
            else:
                wrapped_lines.append(ln)
        if not wrapped_lines:
            return Image.new("RGBA", (width, height), (0, 0, 0, 0))

        fn_cf = self._cfstr(font_name)
        font = self.ct.CTFontCreateWithName(fn_cf, float(font_size), None)
        attrs = self.cf.CFDictionaryCreateMutable(None, 2, None, None)
        self.cf.CFDictionarySetValue(attrs, self.kCTFontAttributeName, font)
        self.cf.CFDictionarySetValue(
            attrs, self.kCTForegroundColorFromContextAttributeName, self.kCFBooleanTrue
        )

        ct_lines = []
        line_metrics = []
        for ln in wrapped_lines:
            s_cf = self._cfstr(ln)
            attr_str = self.cf.CFAttributedStringCreate(None, s_cf, attrs)
            ct_line = self.ct.CTLineCreateWithAttributedString(attr_str)
            ascent = ctypes.c_double()
            descent = ctypes.c_double()
            leading = ctypes.c_double()
            lw = self.ct.CTLineGetTypographicBounds(
                ct_line, ctypes.byref(ascent), ctypes.byref(descent), ctypes.byref(leading)
            )
            ct_lines.append((ct_line, attr_str, s_cf))
            line_metrics.append((lw, ascent.value, descent.value))

        line_gap = int(font_size * 0.32)
        line_heights = [asc + desc for (_lw, asc, desc) in line_metrics]
        total_text_h = sum(line_heights) + line_gap * max(0, len(line_metrics) - 1)
        max_text_w = max(m[0] for m in line_metrics)

        block_bottom = height - margin_v
        block_top = block_bottom - total_text_h

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if pill_bg and max_text_w > 0:
            draw = ImageDraw.Draw(overlay)
            pad_x = int(font_size * 0.75)
            pad_y = int(font_size * 0.45)
            rect_left = int((width - max_text_w) / 2 - pad_x)
            rect_top = int(block_top - pad_y)
            rect_right = int((width + max_text_w) / 2 + pad_x)
            rect_bottom = int(block_bottom + pad_y)
            draw.rounded_rectangle(
                [rect_left, rect_top, rect_right, rect_bottom],
                radius=int(font_size * 0.48),
                fill=(12, 8, 4, 165),
                outline=(255, 200, 90, 95),
                width=2,
            )

        buf = (ctypes.c_ubyte * (width * height * 4))()
        cs = self.cg.CGColorSpaceCreateDeviceRGB()
        ctx = self.cg.CGBitmapContextCreate(
            buf, width, height, 8, width * 4, cs, self.kCGImageAlphaPremultipliedLast
        )

        curr_top_from_top = block_top
        for (ct_line, _attr_str, _s_cf), (lw, asc, desc) in zip(ct_lines, line_metrics):
            baseline_from_top = curr_top_from_top + asc
            cg_y = float(height) - baseline_from_top
            cg_x = (float(width) - lw) / 2.0

            for dx, dy in [(-2.0, -2.0), (2.0, -2.0), (-2.0, 2.0), (2.0, 2.0), (0.0, -2.5)]:
                self.cg.CGContextSetRGBFillColor(ctx, 0.0, 0.0, 0.0, 0.92)
                self.cg.CGContextSetTextPosition(ctx, cg_x + dx, cg_y + dy)
                self.ct.CTLineDraw(ct_line, ctx)

            self.cg.CGContextSetRGBFillColor(ctx, 1.0, 0.97, 0.88, 1.0)
            self.cg.CGContextSetTextPosition(ctx, cg_x, cg_y)
            self.ct.CTLineDraw(ct_line, ctx)

            curr_top_from_top += (asc + desc) + line_gap

        for ct_line, attr_str, s_cf in ct_lines:
            self.cf.CFRelease(ct_line)
            self.cf.CFRelease(attr_str)
            self.cf.CFRelease(s_cf)
        self.cf.CFRelease(attrs)
        self.cf.CFRelease(font)
        self.cf.CFRelease(fn_cf)
        self.cg.CGContextRelease(ctx)
        self.cg.CGColorSpaceRelease(cs)

        text_img = Image.frombuffer("RGBA", (width, height), buf, "raw", "RGBA", 0, 1)
        return Image.alpha_composite(overlay, text_img)


def create_slide_clip(
    image_path: Path,
    out_clip_path: Path,
    duration: float,
    width: int,
    height: int,
    fps: int,
    motion: str = "zoom_in",
) -> None:
    """Create a smooth Ken Burns MP4 clip using native ffmpeg zoompan filter."""
    out_clip_path.parent.mkdir(parents=True, exist_ok=True)
    if not image_path.exists():
        raise FileNotFoundError(f"Slide image not found: {image_path}")

    total_frames = max(1, int(round(duration * fps)))
    overscan_w = int(round(width * 1.14))
    overscan_h = int(round(height * 1.14))

    if motion == "zoom_in":
        zp = (
            f"zoompan=z='1.0+0.10*(on/{total_frames})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={width}x{height}:fps={fps}"
        )
    elif motion == "zoom_out":
        zp = (
            f"zoompan=z='1.10-0.10*(on/{total_frames})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={width}x{height}:fps={fps}"
        )
    elif motion == "pan_right":
        zp = (
            f"zoompan=z='1.10':"
            f"x='(iw-iw/zoom)*(on/{total_frames})':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={width}x{height}:fps={fps}"
        )
    elif motion == "pan_left":
        zp = (
            f"zoompan=z='1.10':"
            f"x='(iw-iw/zoom)*(1.0-on/{total_frames})':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={width}x{height}:fps={fps}"
        )
    else:
        zp = f"scale={width}:{height}"

    vf = (
        f"scale={overscan_w}:{overscan_h}:force_original_aspect_ratio=increase,"
        f"crop={overscan_w}:{overscan_h},{zp}"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-r",
        str(fps),
        "-i",
        str(image_path),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t",
        f"{duration:.3f}",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out_clip_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def resolve_local_lyric_window(slide: dict, offset: float, dur: float) -> tuple[float, float]:
    """Compute (local_start, local_end) within a slide of length `dur` where lyrics should appear."""
    s_start = float(slide["start"])
    s_end = float(slide["end"])
    raw_ls = slide.get("lyric_start")
    raw_le = slide.get("lyric_end")

    local_start = 0.0
    local_end = dur
    if raw_ls is not None:
        val = float(raw_ls)
        local_start = max(0.0, val - s_start if val >= s_start else val)
    if raw_le is not None:
        val = float(raw_le)
        local_end = min(dur, val - s_start if val > s_start else val)
    if local_end <= local_start:
        local_start, local_end = 0.0, dur
    return local_start, local_end


def write_master_srt(slides: list[dict], srt_path: Path) -> None:
    """Write output-timeline SRT file strictly during sung lyric windows (video-use Hard Rule 5)."""
    srt_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    offset = 0.0
    cue_idx = 1
    for s in slides:
        dur = float(s["end"]) - float(s["start"])
        lyric = (s.get("lyric") or "").strip()
        if lyric:
            l_start, l_end = resolve_local_lyric_window(s, offset, dur)
            lines.append(str(cue_idx))
            lines.append(f"{srt_timestamp(offset + l_start)} --> {srt_timestamp(offset + l_end)}")
            lines.append(lyric)
            lines.append("")
            cue_idx += 1
        offset += dur
    srt_path.write_text("\n".join(lines), encoding="utf-8")


def burn_lyrics_onto_segments_and_concat(
    segment_paths: list[Path],
    slides: list[dict],
    subtitle_style: dict,
    edit_dir: Path,
    out_video: Path,
    width: int,
    height: int,
    fps: int,
) -> None:
    """Render CoreText lyric PNGs and composite LAST onto each graded vocal segment via ffmpeg."""
    overlays_dir = edit_dir / "lyrics_overlays"
    captioned_dir = edit_dir / "clips_captioned"
    overlays_dir.mkdir(parents=True, exist_ok=True)
    captioned_dir.mkdir(parents=True, exist_ok=True)

    renderer = CoreTextRenderer()
    font_name = str(subtitle_style.get("font_name", "Kohinoor Telugu Bold"))
    font_size = int(subtitle_style.get("font_size", max(38, int(height * 0.044))))
    margin_v = int(subtitle_style.get("margin_v", int(height * 0.095)))
    uppercase = bool(subtitle_style.get("uppercase", False))
    pill_bg = bool(subtitle_style.get("pill_bg", True))

    overlay_pngs: list[Path | None] = []
    for idx, slide in enumerate(slides):
        lyric = (slide.get("lyric") or "").strip()
        if uppercase:
            lyric = lyric.upper()
        if not lyric:
            overlay_pngs.append(None)
            continue
        png_path = overlays_dir / f"lyric_{idx:02d}.png"
        img = renderer.render_caption_overlay(
            text=lyric,
            width=width,
            height=height,
            font_name=font_name,
            font_size=font_size,
            margin_v=margin_v,
            pill_bg=pill_bg,
        )
        img.save(png_path)
        overlay_pngs.append(png_path)

    def _composite_one(args_tuple: tuple[int, Path, Path | None, dict]) -> Path:
        idx, seg_path, png_path, slide = args_tuple
        out_seg = captioned_dir / f"cap_{idx:02d}.mp4"
        if png_path is None:
            # Instrumental / music-only cut: no lyrics burned on screen!
            shutil.copy2(seg_path, out_seg)
            return out_seg
        dur = float(slide["end"]) - float(slide["start"])
        l_start, l_end = resolve_local_lyric_window(slide, 0.0, dur)
        fade_in_st = max(0.0, l_start)
        fade_out_st = max(fade_in_st + 0.1, l_end - 0.25)
        fc = (
            f"[1:v]format=rgba,"
            f"fade=t=in:st={fade_in_st:.3f}:d=0.25:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d=0.25:alpha=1[ov];"
            f"[0:v][ov]overlay=0:0:enable='between(t,{fade_in_st:.3f},{l_end:.3f})':shortest=1[outv]"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(seg_path),
            "-loop",
            "1",
            "-r",
            str(fps),
            "-i",
            str(png_path),
            "-filter_complex",
            fc,
            "-map",
            "[outv]",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(out_seg),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return out_seg

    tasks = [
        (i, segment_paths[i], overlay_pngs[i], slides[i]) for i in range(len(slides))
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        captioned_paths = list(pool.map(_composite_one, tasks))

    concat_list = edit_dir / "_concat_captioned.txt"
    concat_list.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in captioned_paths), encoding="utf-8"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out_video),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    concat_list.unlink(missing_ok=True)


def mux_external_audio(video_in: Path, audio_in: Path, video_out: Path) -> None:
    """Mux an external song audio file onto the rendered video with loudnorm and end fade."""
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_in),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    dur = float(probe.stdout.strip())
    fade_out_st = max(0.0, dur - 1.5)
    af = (
        f"afade=t=in:st=0:d=0.25,"
        f"afade=t=out:st={fade_out_st:.3f}:d=1.5,"
        f"loudnorm=I=-14:TP=-1.0:LRA=11"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_in),
        "-i",
        str(audio_in),
        "-t",
        f"{dur:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-af",
        af,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-shortest",
        "-movflags",
        "+faststart",
        str(video_out),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def append_project_memory(edit_dir: Path, storyboard: dict, out_path: Path) -> None:
    """Append session history to edit/project.md per video-use convention."""
    proj_md = edit_dir / "project.md"
    today = datetime.date.today().isoformat()
    title = storyboard.get("title", "Untitled Lyric Video")
    slides = storyboard.get("slides", [])
    total_dur = sum(float(s["end"]) - float(s["start"]) for s in slides)
    entry = (
        f"\n## Session — {today} ({title})\n\n"
        f"**Strategy:** Generated {len(slides)}-slide audio-synced lyric video "
        f"({total_dur:.2f}s total) using style anchor: `{storyboard.get('style_anchor', '')}`.\n"
        f"**Decisions:** Grade `{storyboard.get('grade', 'warm_cinematic')}`, "
        f"resolution `{storyboard.get('resolution', [1920, 1080])}`, "
        f"audio `{storyboard.get('audio_path')}`, synchronized lyrics burned last in pipeline.\n"
        f"**Export:** `{out_path}`\n"
    )
    if proj_md.exists():
        proj_md.write_text(proj_md.read_text(encoding="utf-8") + entry, encoding="utf-8")
    else:
        proj_md.write_text(f"# Video-Use Project Memory\n{entry}", encoding="utf-8")


def main() -> None:
    ensure_ffmpeg_on_path()
    ap = argparse.ArgumentParser(description="Build a lyric slideshow video using video-use")
    ap.add_argument("--storyboard", type=Path, required=True, help="Path to storyboard.json")
    ap.add_argument("-o", "--output", type=Path, default=None, help="Final output MP4 path")
    ap.add_argument("--preview", action="store_true", help="Render in video-use preview mode")
    args = ap.parse_args()

    sb_path = args.storyboard.resolve()
    if not sb_path.exists():
        sys.exit(f"Storyboard not found: {sb_path}")

    project_dir = sb_path.parent
    storyboard = json.loads(sb_path.read_text(encoding="utf-8"))

    res = storyboard.get("resolution") or [1920, 1080]
    width, height = int(res[0]), int(res[1])
    fps = int(storyboard.get("fps", 30))
    grade = storyboard.get("grade", "warm_cinematic")
    subtitle_style = storyboard.get("subtitle_style") or {}
    raw_slides = storyboard.get("slides") or []
    if not raw_slides:
        sys.exit("No slides defined in storyboard.json")

    slides = expand_slides_for_music_interludes(raw_slides)

    sources_dir = project_dir / "sources"
    edit_dir = project_dir / "edit"
    sources_dir.mkdir(parents=True, exist_ok=True)
    edit_dir.mkdir(parents=True, exist_ok=True)

    edl_sources: dict[str, str] = {}
    edl_ranges: list[dict] = []
    total_duration = 0.0

    print(f"[1/4] Building {len(slides)} motion slide clips ({width}x{height} @ {fps}fps)...")

    def _build_clip_task(idx_slide: tuple[int, dict]) -> tuple[int, str, Path, float, dict]:
        idx, slide = idx_slide
        sid = slide.get("id") or f"slide_{idx:02d}"
        img_rel = slide["image_path"]
        img_path = Path(img_rel) if Path(img_rel).is_absolute() else (project_dir / img_rel).resolve()
        dur = float(slide["end"]) - float(slide["start"])
        clip_path = sources_dir / f"{sid}.mp4"
        motion = slide.get("motion", "zoom_in")
        tag = "MUSIC" if not (slide.get("lyric") or "").strip() else "LYRIC"
        print(f"  - {sid} [{tag}]: {dur:.2f}s ({motion}) <- {img_path.name}", flush=True)
        create_slide_clip(
            image_path=img_path,
            out_clip_path=clip_path,
            duration=dur,
            width=width,
            height=height,
            fps=fps,
            motion=motion,
        )
        return idx, sid, clip_path, dur, slide

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_build_clip_task, enumerate(slides, start=1)))

    for idx, sid, clip_path, dur, slide in results:
        edl_sources[sid] = str(clip_path.resolve())
        edl_ranges.append(
            {
                "source": sid,
                "start": 0.0,
                "end": round(dur, 3),
                "beat": slide.get("section") or f"SLIDE_{idx:02d}",
                "quote": slide.get("lyric", ""),
                "reason": slide.get("meaning", "Visual beat"),
            }
        )
        total_duration += dur

    srt_path = edit_dir / "master.srt"
    write_master_srt(slides, srt_path)
    print(f"[2/4] Wrote synchronized lyrics SRT -> {srt_path}")

    edl = {
        "version": 1,
        "sources": edl_sources,
        "ranges": edl_ranges,
        "grade": grade,
        "overlays": storyboard.get("overlays", []),
        "subtitles": str(srt_path.resolve()),
        "total_duration_s": round(total_duration, 3),
    }
    edl_path = edit_dir / "edl.json"
    edl_path.write_text(json.dumps(edl, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"      Wrote video-use EDL -> {edl_path}")

    graded_base = edit_dir / "graded_base.mp4"
    render_cmd = [
        sys.executable,
        str(VIDEO_USE_RENDER),
        str(edl_path),
        "-o",
        str(graded_base),
        "--no-subtitles",
        "--no-loudnorm",
        "--fps",
        str(fps),
    ]
    if args.preview:
        render_cmd.append("--preview")

    print(f"[3/4] Running video-use render pipeline (grade='{grade}')...")
    subprocess.run(render_cmd, check=True, env=os.environ.copy())

    clips_dir = edit_dir / ("clips_preview" if args.preview else "clips_graded")
    segment_paths = [
        clips_dir / f"seg_{i:02d}_{r['source']}.mp4" for i, r in enumerate(edl_ranges)
    ]

    edit_final = edit_dir / ("preview.mp4" if args.preview else "final.mp4")
    audio_path = resolve_audio_path(storyboard.get("audio_path"), project_dir)

    if audio_path is not None and audio_path.exists():
        lyric_temp = edit_dir / "_lyrics_burned.mp4"
        print(f"[4/4] Burning synchronized CoreText lyrics LAST + muxing '{audio_path.name}'...")
        burn_lyrics_onto_segments_and_concat(
            segment_paths=segment_paths,
            slides=slides,
            subtitle_style=subtitle_style,
            edit_dir=edit_dir,
            out_video=lyric_temp,
            width=width,
            height=height,
            fps=fps,
        )
        mux_external_audio(lyric_temp, audio_path, edit_final)
        lyric_temp.unlink(missing_ok=True)
    else:
        print("[4/4] Burning synchronized CoreText lyrics LAST onto graded video...")
        burn_lyrics_onto_segments_and_concat(
            segment_paths=segment_paths,
            slides=slides,
            subtitle_style=subtitle_style,
            edit_dir=edit_dir,
            out_video=edit_final,
            width=width,
            height=height,
            fps=fps,
        )

    graded_base.unlink(missing_ok=True)

    final_out = args.output.resolve() if args.output else edit_final
    if final_out != edit_final:
        final_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(edit_final, final_out)

    append_project_memory(edit_dir, storyboard, final_out)
    size_mb = final_out.stat().st_size / (1024 * 1024)
    print(f"\nSUCCESS! Final lyric video exported to:\n  - {final_out} ({size_mb:.2f} MB)\n  - {edit_final}")


if __name__ == "__main__":
    main()
