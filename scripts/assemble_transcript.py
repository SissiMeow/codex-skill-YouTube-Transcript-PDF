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
WORD_RE = re.compile(r"\w+")


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
        end = float(item.get("end", start))
        segments.append({"start": start, "end": max(start, end), "text": text})
    return deduplicate_segments(segments)


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


def should_flush_on_gap(current_words: int, parts: list[dict], gap_seconds: float, actual_gap: float) -> bool:
    if actual_gap < gap_seconds:
        return False
    if current_words >= 30:
        return True
    if current_words >= 12:
        return True
    if parts and looks_like_sentence_end(parts[-1]["text"]):
        return True
    return actual_gap >= max(gap_seconds * 2, 12.0)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def shared_word_ratio(left: str, right: str) -> float:
    left_words = left.lower().split()
    right_words = right.lower().split()
    if not left_words or not right_words:
        return 0.0
    overlap = len(set(left_words) & set(right_words))
    return overlap / max(len(set(left_words)), len(set(right_words)), 1)


def suffix_prefix_word_overlap(left: str, right: str) -> int:
    left_words = left.split()
    right_words = right.split()
    max_len = min(len(left_words), len(right_words))
    for size in range(max_len, 2, -1):
        if [word.lower() for word in left_words[-size:]] == [word.lower() for word in right_words[:size]]:
            return size
    return 0


def merge_segment_text(previous: str, current: str) -> str:
    if not previous:
        return current
    if current.lower() == previous.lower():
        return previous
    if current.lower().startswith(previous.lower()):
        return current
    if previous.lower().startswith(current.lower()):
        return previous
    overlap = suffix_prefix_word_overlap(previous, current)
    if overlap:
        return " ".join(previous.split() + current.split()[overlap:])
    if shared_word_ratio(previous, current) >= 0.85:
        return previous if len(previous) >= len(current) else current
    return f"{previous} {current}"


def should_merge_with_previous(previous: dict, current: dict) -> bool:
    previous_text = previous["text"]
    current_text = current["text"]
    overlap = suffix_prefix_word_overlap(previous_text, current_text)
    if overlap:
        return True
    if current_text.lower() == previous_text.lower():
        return True
    if current_text.lower().startswith(previous_text.lower()) or previous_text.lower().startswith(current_text.lower()):
        return True
    return shared_word_ratio(previous_text, current_text) >= 0.85


def deduplicate_segments(segments: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    for segment in segments:
        if not deduped:
            deduped.append(segment)
            continue
        previous = deduped[-1]
        if should_merge_with_previous(previous, segment):
            previous["text"] = normalize_text(merge_segment_text(previous["text"], segment["text"]))
            previous["end"] = max(float(previous.get("end", previous["start"])), float(segment.get("end", segment["start"])))
            continue
        deduped.append(segment)
    return deduped


def flush_paragraph(parts: list[dict], paragraphs: list[dict]) -> None:
    if not parts:
        return
    paragraph = parts[0]["text"]
    for part in parts[1:]:
        paragraph = merge_segment_text(paragraph, part["text"])
    paragraph = normalize_text(paragraph)
    if not paragraph:
        return
    paragraphs.append(
        {
            "type": "paragraph",
            "start": parts[0]["start"],
            "end": max(float(part.get("end", part["start"])) for part in parts),
            "word_count": word_count(paragraph),
            "text": paragraph,
        }
    )
    parts.clear()

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
    blocks: list[dict] = []
    current_parts: list[dict] = []
    current_words = 0
    previous_end: float | None = None

    for segment in segments:
        start = segment["start"]
        end = float(segment.get("end", start))
        text = segment["text"]

        while chapter_index < len(chapter_breaks) and start >= chapter_breaks[chapter_index]:
            if current_parts and current_parts[0]["start"] < chapter_breaks[chapter_index]:
                flush_paragraph(current_parts, blocks)
                current_words = 0
            chapter_index += 1

        actual_gap = (start - previous_end) if previous_end is not None else 0.0
        if previous_end is not None and should_flush_on_gap(current_words, current_parts, gap_seconds, actual_gap):
            flush_paragraph(current_parts, blocks)
            current_words = 0

        while start >= next_marker:
            flush_paragraph(current_parts, blocks)
            current_words = 0
            blocks.append(
                {
                    "type": "marker",
                    "start": float(next_marker),
                    "end": float(next_marker),
                    "word_count": 0,
                    "text": format_marker(next_marker),
                }
            )
            next_marker += interval_seconds

        current_parts.append({"start": start, "end": end, "text": text})
        current_words += word_count(text)

        if current_words >= max_paragraph_words and looks_like_sentence_end(text):
            flush_paragraph(current_parts, blocks)
            current_words = 0

        previous_end = end

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
