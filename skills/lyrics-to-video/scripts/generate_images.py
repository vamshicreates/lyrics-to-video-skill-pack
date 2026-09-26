#!/usr/bin/env python3
"""Batch-generate slide images from storyboard.json via Gemini / Nano Banana API.

Note: In Antigravity, the primary zero-config method is calling the built-in
`generate_image` tool for each slide and copying the resulting artifact into
`projects/<song_slug>/images/slide_NN.png`. This script is provided as a fast
batch alternative when `GEMINI_API_KEY` or `GOOGLE_API_KEY` is set in the
environment or `.env`.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path
import requests


def load_api_key(project_dir: Path) -> str | None:
    for key_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        if os.environ.get(key_name):
            return os.environ[key_name]
    for env_candidate in (
        project_dir / ".env",
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent.parent / "video-use" / ".env",
    ):
        if env_candidate.exists():
            for line in env_candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(("GEMINI_API_KEY=", "GOOGLE_API_KEY=")):
                    val = line.split("=", 1)[1].strip().strip("'\"")
                    if val:
                        return val
    return None


def generate_via_gemini_image(prompt: str, api_key: str, model: str, out_path: Path) -> None:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    resp = requests.post(url, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                raw = base64.b64decode(inline["data"])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(raw)
                return
    raise RuntimeError(f"No image returned from {model} for prompt: {prompt[:80]}...")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate slide images from storyboard.json")
    ap.add_argument("--storyboard", type=Path, required=True, help="Path to storyboard.json")
    ap.add_argument(
        "--model",
        default="gemini-2.5-flash-image",
        help="Model ID (default: gemini-2.5-flash-image / Nano Banana)",
    )
    ap.add_argument("--force", action="store_true", help="Regenerate even if image file exists")
    args = ap.parse_args()

    sb_path = args.storyboard.resolve()
    project_dir = sb_path.parent
    storyboard = json.loads(sb_path.read_text(encoding="utf-8"))

    api_key = load_api_key(project_dir)
    if not api_key:
        sys.exit(
            "No GEMINI_API_KEY or GOOGLE_API_KEY found in environment or .env.\n"
            "Use the agent's built-in `generate_image` tool to generate each slide image."
        )

    slides = storyboard.get("slides", [])
    for idx, slide in enumerate(slides, start=1):
        sid = slide.get("id") or f"slide_{idx:02d}"
        img_rel = slide.get("image_path") or f"images/{sid}.png"
        out_path = Path(img_rel) if Path(img_rel).is_absolute() else (project_dir / img_rel).resolve()
        if out_path.exists() and not args.force:
            print(f"[{idx}/{len(slides)}] Skipping existing {out_path.name}")
            continue
        prompt = slide["prompt"]
        print(f"[{idx}/{len(slides)}] Generating {out_path.name} with {args.model}...")
        generate_via_gemini_image(prompt, api_key, args.model, out_path)
        print(f"  -> Saved {out_path}")


if __name__ == "__main__":
    main()
