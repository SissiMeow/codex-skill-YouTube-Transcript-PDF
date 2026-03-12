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
        "--metadata-output",
        help="Optional JSON path for paragraph metadata with start times.",
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
    parser.add_argument(
        "--chapter-breaks-json",
        help="Optional JSON file with chapter start_time values to force paragraph breaks.",
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


def load_chapter_breaks(path: str | None) -> list[float]:
    if not path:
        return []
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("chapter-breaks-json must contain a list")
    breaks = []
    for item in data:
        if not isinstance(item, dict):
            continue
        start_time = item.get("start_time")
        if start_time is None:
            continue
        breaks.append(float(start_time))
    return sorted(set(breaks))


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


def flush_paragraph(parts: list[dict], paragraphs: list[dict]) -> None:
    if not parts:
        return
    paragraph = " ".join(part["text"] for part in parts)
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    if not paragraph:
        return
    paragraphs.append({"type": "paragraph", "start": parts[0]["start"], "text": paragraph})
    parts.clear()


def assemble_text(
    segments: list[dict],
    interval_minutes: int,
    max_paragraph_words: int,
    gap_seconds: float,
) -> str:
    return assemble_blocks(
        segments,
        interval_minutes=interval_minutes,
        max_paragraph_words=max_paragraph_words,
        gap_seconds=gap_seconds,
    )


def assemble_blocks(
    segments: list[dict],
    interval_minutes: int,
    max_paragraph_words: int,
    gap_seconds: float,
    chapter_breaks: list[float] | None = None,
) -> list[dict]:
    if not segments:
        return []

    chapter_breaks = chapter_breaks or []
    chapter_index = 0
    interval_seconds = max(1, interval_minutes) * 60
    next_marker = interval_seconds
    blocks: list[str] = []
    current_parts: list[dict] = []
    current_words = 0
    previous_start: float | None = None
    previous_text = ""

    for segment in segments:
        start = segment["start"]
        text = segment["text"]
        if text == previous_text:
            continue

        while chapter_index < len(chapter_breaks) and start >= chapter_breaks[chapter_index]:
            if current_parts and current_parts[0]["start"] < chapter_breaks[chapter_index]:
                flush_paragraph(current_parts, blocks)
                current_words = 0
            chapter_index += 1

        if previous_start is not None and start - previous_start >= gap_seconds and current_words >= 40:
            flush_paragraph(current_parts, blocks)
            current_words = 0

        while start >= next_marker:
            flush_paragraph(current_parts, blocks)
            current_words = 0
            blocks.append({"type": "marker", "start": float(next_marker), "text": format_marker(next_marker)})
            next_marker += interval_seconds

        current_parts.append({"start": start, "text": text})
        current_words += len(text.split())

        if current_words >= max_paragraph_words and looks_like_sentence_end(text):
            flush_paragraph(current_parts, blocks)
            current_words = 0

        previous_start = start
        previous_text = text

    flush_paragraph(current_parts, blocks)
    return blocks


def assemble_text(
    segments: list[dict],
    interval_minutes: int,
    max_paragraph_words: int,
    gap_seconds: float,
    chapter_breaks: list[float] | None = None,
) -> str:
    blocks = assemble_blocks(
        segments,
        interval_minutes=interval_minutes,
        max_paragraph_words=max_paragraph_words,
        gap_seconds=gap_seconds,
        chapter_breaks=chapter_breaks,
    )
    texts = [block["text"] for block in blocks]
    return "\n\n".join(texts).strip() + "\n"


def main() -> None:
    args = parse_args()
    segments = load_segments(Path(args.input))
    transcript = assemble_text(
        segments,
        interval_minutes=args.interval_minutes,
        max_paragraph_words=args.max_paragraph_words,
        gap_seconds=args.gap_seconds,
        chapter_breaks=load_chapter_breaks(args.chapter_breaks_json),
    )
    if args.output:
        Path(args.output).write_text(transcript)
    else:
        print(transcript, end="")
    if args.metadata_output:
        blocks = assemble_blocks(
            segments,
            interval_minutes=args.interval_minutes,
            max_paragraph_words=args.max_paragraph_words,
            gap_seconds=args.gap_seconds,
            chapter_breaks=load_chapter_breaks(args.chapter_breaks_json),
        )
        Path(args.metadata_output).write_text(json.dumps(blocks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
