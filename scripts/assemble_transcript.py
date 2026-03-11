#!/usr/bin/env python3
"""Assemble timed transcript segments into readable prose."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


NOISE_PATTERNS = [
    re.compile(r"^\[music\]$", re.IGNORECASE),
    re.compile(r"^\[applause\]$", re.IGNORECASE),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Format timed transcript segments into readable text.",
    )
    parser.add_argument("input", help="Path to a JSON file of transcript segments")
    parser.add_argument(
        "--output",
        help="Path to write the transcript. Defaults to stdout.",
    )
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=20,
        help="Insert markers roughly every N minutes (default: 20).",
    )
    parser.add_argument(
        "--max-paragraph-words",
        type=int,
        default=140,
        help="Target upper bound for paragraph length (default: 140).",
    )
    parser.add_argument(
        "--gap-seconds",
        type=float,
        default=7.0,
        help="Start a new paragraph after time gaps larger than this (default: 7).",
    )
    return parser.parse_args()


def load_segments(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Input must be a JSON list of segments.")
    segments = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = normalize_text(str(item.get("text", "")))
        if not text or is_noise(text):
            continue
        start = float(item.get("start", 0))
        segments.append({"start": start, "text": text})
    return segments


def normalize_text(text: str) -> str:
    text = text.replace(">>", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_noise(text: str) -> bool:
    return any(pattern.match(text) for pattern in NOISE_PATTERNS)


def format_marker(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"


def looks_like_sentence_end(text: str) -> bool:
    return text.endswith((".", "?", "!", '"', "'"))


def flush_paragraph(parts: list[str], paragraphs: list[str]) -> None:
    if not parts:
        return
    paragraph = " ".join(parts)
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    if not paragraph:
        return
    paragraphs.append(paragraph)
    parts.clear()


def assemble_text(
    segments: list[dict],
    interval_minutes: int,
    max_paragraph_words: int,
    gap_seconds: float,
) -> str:
    if not segments:
        return ""

    interval_seconds = max(1, interval_minutes) * 60
    next_marker = interval_seconds
    blocks: list[str] = []
    current_parts: list[str] = []
    current_words = 0
    previous_start: float | None = None
    previous_text = ""

    for segment in segments:
        start = segment["start"]
        text = segment["text"]
        if text == previous_text:
            continue

        if previous_start is not None and start - previous_start >= gap_seconds and current_words >= 40:
            flush_paragraph(current_parts, blocks)
            current_words = 0

        while start >= next_marker:
            flush_paragraph(current_parts, blocks)
            current_words = 0
            blocks.append(format_marker(next_marker))
            next_marker += interval_seconds

        current_parts.append(text)
        current_words += len(text.split())

        if current_words >= max_paragraph_words and looks_like_sentence_end(text):
            flush_paragraph(current_parts, blocks)
            current_words = 0

        previous_start = start
        previous_text = text

    flush_paragraph(current_parts, blocks)
    return "\n\n".join(blocks).strip() + "\n"


def main() -> None:
    args = parse_args()
    segments = load_segments(Path(args.input))
    transcript = assemble_text(
        segments,
        interval_minutes=args.interval_minutes,
        max_paragraph_words=args.max_paragraph_words,
        gap_seconds=args.gap_seconds,
    )
    if args.output:
        Path(args.output).write_text(transcript)
    else:
        print(transcript, end="")


if __name__ == "__main__":
    main()
