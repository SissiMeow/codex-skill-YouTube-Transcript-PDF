#!/usr/bin/env python3
"""Run offline validation checks for the youtube-transcript skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run offline validation checks for the youtube-transcript skill.",
    )
    parser.add_argument(
        "--skill-root",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="Path to the youtube-transcript skill root.",
    )
    return parser.parse_args()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(left, right, message: str) -> None:
    if left != right:
        raise AssertionError(f"{message}: expected {right!r}, got {left!r}")


def test_fetch_parser(fetch_module, fixtures: Path) -> None:
    segments = fetch_module.parse_vtt(fixtures / "sample_captions.vtt")
    assert_equal(len(segments), 2, "sample VTT should collapse into two segments")
    assert_equal(
        segments[0]["text"],
        "welcome to the show today we are talking about retail.",
        "overlapping caption windows should merge cleanly",
    )
    quality = fetch_module.assess_segments(
        segments=segments,
        duration_seconds=12.0,
        minimum_punctuation_density=0.003,
    )
    assert_true(quality["coverage_ratio"] >= 0.9, "sample VTT should cover most of the short clip")


def test_assemble_flow(assemble_module, fixtures: Path) -> tuple[list[dict], str]:
    segments = assemble_module.load_segments(fixtures / "segments_markers.json")
    blocks = assemble_module.assemble_blocks(
        segments,
        interval_minutes=20,
        max_paragraph_words=140,
        gap_seconds=5.0,
        chapter_breaks=assemble_module.load_chapter_breaks(fixtures / "chapters.json"),
    )
    paragraph_blocks = [block for block in blocks if block["type"] == "paragraph"]
    marker_blocks = [block for block in blocks if block["type"] == "marker"]
    assert_equal(len(paragraph_blocks), 3, "synthetic marker fixture should produce three paragraphs")
    assert_equal(len(marker_blocks), 1, "synthetic marker fixture should insert one coarse marker")
    assert_equal(marker_blocks[0]["text"], "[00:20:00]", "marker should land at the 20 minute boundary")
    assert_equal(
        paragraph_blocks[0]["text"],
        "welcome to the show today we are talking about retail.",
        "first paragraph should merge overlapping caption windows",
    )
    transcript = assemble_module.assemble_text(
        segments,
        interval_minutes=20,
        max_paragraph_words=140,
        gap_seconds=5.0,
        chapter_breaks=assemble_module.load_chapter_breaks(fixtures / "chapters.json"),
    )
    assert_true("[00:20:00]" in transcript, "assembled transcript text should retain marker blocks")
    return blocks, transcript


def build_long_metadata_blocks(blocks: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    offset = 0.0
    for repeat in range(45):
        for block in blocks:
            copied = dict(block)
            copied["start"] = float(copied.get("start", 0)) + offset
            copied["end"] = float(copied.get("end", copied["start"])) + offset
            if copied["type"] == "paragraph":
                copied["text"] = f"{copied['text']} Repetition {repeat + 1} keeps the render test multi-page."
                copied["word_count"] = len(copied["text"].split())
            expanded.append(copied)
        offset += 35.0
    return expanded


def test_pdf_render(render_module, blocks: list[dict], fixtures: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="youtube-transcript-validate-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        transcript_path = temp_dir / "transcript.txt"
        metadata_path = temp_dir / "transcript_metadata.json"
        output_path = temp_dir / "validation.pdf"

        expanded_blocks = build_long_metadata_blocks(blocks)
        transcript_text = "\n\n".join(block["text"] for block in expanded_blocks) + "\n"
        transcript_path.write_text(transcript_text)
        metadata_path.write_text(json.dumps(expanded_blocks, ensure_ascii=False, indent=2) + "\n")

        args = argparse.Namespace(
            title="Validation Transcript",
            date="2026-03-12",
            channel="Codex Validation Channel",
            source_url=None,
            summary_file=str(fixtures / "summary.txt"),
            chapters_json=str(fixtures / "chapters.json"),
            transcript=str(transcript_path),
            transcript_metadata_json=str(metadata_path),
            output=str(output_path),
        )
        render_module.render_pdf(args)

        pdf_bytes = output_path.read_bytes()
        assert_true(output_path.exists(), "render validation should write a PDF")
        assert_true(len(pdf_bytes) > 5000, "rendered PDF should be non-trivially sized")
        assert_true(b"Validation Transcript" in pdf_bytes, "rendered PDF should include the document title")
        assert_true(b"Codex Validation Channel" in pdf_bytes, "rendered PDF should include channel metadata")
        assert_true(
            b"Sissi Skill - YouTube Transcript to PDF" in pdf_bytes,
            "multi-page PDF should include the repeated page label",
        )


def main() -> None:
    args = parse_args()
    skill_root = args.skill_root.resolve()
    scripts_dir = skill_root / "scripts"
    fixtures = skill_root / "tests" / "fixtures"

    fetch_module = load_module("fetch_youtube_transcript", scripts_dir / "fetch_youtube_transcript.py")
    assemble_module = load_module("assemble_transcript", scripts_dir / "assemble_transcript.py")
    render_module = load_module("render_blog_pdf", scripts_dir / "render_blog_pdf.py")

    test_fetch_parser(fetch_module, fixtures)
    blocks, _ = test_assemble_flow(assemble_module, fixtures)
    test_pdf_render(render_module, blocks, fixtures)

    print("Validation passed: youtube-transcript skill offline checks succeeded.")


if __name__ == "__main__":
    main()
