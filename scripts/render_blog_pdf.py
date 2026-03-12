#!/usr/bin/env python3
"""Render a blog-style transcript PDF with no external PDF dependency."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from AppKit import NSFont, NSFontAttributeName
    from Foundation import NSString

    HAS_APPKIT = True
except Exception:
    HAS_APPKIT = False


PAGE_WIDTH = 612
PAGE_HEIGHT = 792
LEFT_MARGIN = 72
RIGHT_MARGIN = 72
TOP_MARGIN = 72
BOTTOM_MARGIN = 72
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
FOOTER_RULE_Y = BOTTOM_MARGIN / 2
BODY_BOTTOM_Y = FOOTER_RULE_Y
HEADER_RULE_Y = PAGE_HEIGHT - FOOTER_RULE_Y
HEADER_LABEL_GAP = 10

FONT_MAP = {
    "sans": "F1",
    "sans-bold": "F2",
    "serif": "F3",
}

CHAR_WIDTHS = {
    "sans": 0.52,
    "sans-bold": 0.56,
    "serif": 0.50,
}

NS_FONT_NAMES = {
    "sans": "Helvetica",
    "sans-bold": "Helvetica-Bold",
    "serif": "Times-Roman",
}

FONT_CACHE: dict[tuple[str, int], object] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a polished transcript PDF.",
    )
    parser.add_argument("--title", required=True, help="Document title")
    parser.add_argument("--date", required=True, help="Publication date")
    parser.add_argument("--channel", help="Channel or source name")
    parser.add_argument("--source-url", help="Source URL")
    parser.add_argument("--summary-file", help="Path to a summary text file")
    parser.add_argument("--chapters-json", help="Path to a chapters JSON file")
    parser.add_argument("--transcript", required=True, help="Transcript text file")
    parser.add_argument(
        "--transcript-metadata-json",
        help="Optional JSON produced by assemble_transcript.py with paragraph start times.",
    )
    parser.add_argument(
        "--output",
        help="Output PDF path. Defaults to ./<slug>.pdf",
    )
    return parser.parse_args()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "youtube-transcript"


def escape_pdf_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_summary(path: str | None) -> list[str]:
    if not path:
        return []
    text = Path(path).read_text().strip()
    if not text:
        return []
    return [normalize_text(chunk) for chunk in text.split("\n\n") if normalize_text(chunk)]


def load_chapters(path: str | None) -> list[dict]:
    if not path:
        return []
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("chapters-json must contain a list")
    chapters = []
    for item in data:
        if not isinstance(item, dict):
            continue
        chapters.append(
            {
                "title": str(item.get("title", "")).strip(),
                "start_time": float(item.get("start_time", 0)),
            }
        )
    return [chapter for chapter in chapters if chapter["title"]]


def filter_close_chapters(chapters: list[dict], min_gap_seconds: float = 60.0) -> list[dict]:
    if not chapters:
        return []
    filtered = [chapters[0]]
    for chapter in chapters[1:]:
        if chapter["start_time"] - filtered[-1]["start_time"] < min_gap_seconds:
            filtered[-1] = chapter
        else:
            filtered.append(chapter)
    return filtered


def load_transcript(path: str) -> list[str]:
    text = Path(path).read_text().strip()
    if not text:
        return []
    return [block.strip() for block in text.split("\n\n") if block.strip()]


def load_transcript_metadata(path: str | None) -> list[dict]:
    if not path:
        return []
    data = json.loads(Path(path).read_text())
    if not isinstance(data, list):
        raise ValueError("transcript-metadata-json must contain a list")
    blocks = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        blocks.append(
            {
                "type": str(item.get("type", "paragraph")),
                "start": float(item.get("start", 0)),
                "text": text,
            }
        )
    return blocks


def format_time(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def is_marker(block: str) -> bool:
    return bool(re.fullmatch(r"\[[0-9]{2}:[0-9]{2}:[0-9]{2}\]", block))


def estimate_width(text: str, font_key: str, size: int) -> float:
    if HAS_APPKIT:
        cache_key = (font_key, size)
        font = FONT_CACHE.get(cache_key)
        if font is None:
            font = NSFont.fontWithName_size_(NS_FONT_NAMES[font_key], size)
            FONT_CACHE[cache_key] = font
        if font is not None:
            attrs = {NSFontAttributeName: font}
            return NSString.stringWithString_(text).sizeWithAttributes_(attrs).width
    return len(text) * size * CHAR_WIDTHS[font_key]


def wrap_text(text: str, font_key: str, size: int, width: float) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if estimate_width(candidate, font_key, size) <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


@dataclass
class TextStyle:
    font_key: str
    size: int
    leading: int
    color: tuple[float, float, float]
    justify: bool = False


class PDFDocument:
    def __init__(self) -> None:
        self.pages: list[list[str]] = []
        self.current_ops: list[str] = []
        self.cursor_y = PAGE_HEIGHT - TOP_MARGIN
        self.page_number = 0
        self.body_start_index = 0
        self.new_page()

    def shift_operation_y(self, op: str, delta: float) -> str:
        def shift_text(match: re.Match[str]) -> str:
            x = match.group(1)
            y = float(match.group(2)) - delta
            return f"1 0 0 1 {x} {y:.2f} Tm"

        def shift_line(match: re.Match[str]) -> str:
            x1 = match.group(1)
            y1 = float(match.group(2)) - delta
            x2 = match.group(3)
            y2 = float(match.group(4)) - delta
            return f"{x1} {y1:.2f} m {x2} {y2:.2f} l"

        op = re.sub(r"1 0 0 1 ([0-9.]+) ([0-9.]+) Tm", shift_text, op)
        op = re.sub(r"([0-9.]+) ([0-9.]+) m ([0-9.]+) ([0-9.]+) l", shift_line, op)
        return op

    def close_page(self) -> None:
        if not self.current_ops:
            return
        if self.page_number > 1:
            slack = max(0.0, self.cursor_y - BODY_BOTTOM_Y)
            if slack > 0:
                self.current_ops[self.body_start_index :] = [
                    self.shift_operation_y(op, slack)
                    for op in self.current_ops[self.body_start_index :]
                ]
        self.current_ops.append(
            f"q 0.85 G 1 w {LEFT_MARGIN} {FOOTER_RULE_Y:.2f} m "
            f"{PAGE_WIDTH - RIGHT_MARGIN} {FOOTER_RULE_Y:.2f} l S Q"
        )
        self.pages.append(self.current_ops)

    def new_page(self) -> None:
        if self.current_ops:
            self.close_page()
        self.current_ops = []
        self.cursor_y = PAGE_HEIGHT - TOP_MARGIN
        self.page_number += 1
        if self.page_number > 1:
            self.draw_page_label()
        self.body_start_index = len(self.current_ops)

    def draw_page_label(self) -> None:
        style = TextStyle("sans", 9, 12, (0.45, 0.45, 0.45))
        label_y = HEADER_RULE_Y + HEADER_LABEL_GAP
        self.write_line("Sissi Skill - YouTube Transcript to PDF", LEFT_MARGIN, label_y, style)
        self.current_ops.append(
            f"q 0.85 G 1 w {LEFT_MARGIN} {HEADER_RULE_Y:.2f} m "
            f"{PAGE_WIDTH - RIGHT_MARGIN} {HEADER_RULE_Y:.2f} l S Q"
        )
        self.cursor_y = HEADER_RULE_Y - 28

    def ensure_space(self, needed: float) -> None:
        if self.cursor_y - needed < BODY_BOTTOM_Y:
            self.new_page()

    def draw_rule(self) -> None:
        y = self.cursor_y
        self.current_ops.append(
            f"q 0.85 G 1 w {LEFT_MARGIN} {y:.2f} m {PAGE_WIDTH - RIGHT_MARGIN} {y:.2f} l S Q"
        )

    def write_line(self, text: str, x: float, y: float, style: TextStyle) -> None:
        r, g, b = style.color
        font_name = FONT_MAP[style.font_key]
        escaped = escape_pdf_text(text)
        self.current_ops.append(
            "BT "
            f"/{font_name} {style.size} Tf "
            f"{r:.3f} {g:.3f} {b:.3f} rg "
            f"1 0 0 1 {x:.2f} {y:.2f} Tm "
            f"({escaped}) Tj ET"
        )

    def write_justified_line(self, text: str, y: float, style: TextStyle) -> None:
        spaces = text.count(" ")
        if spaces <= 0:
            self.write_line(text, LEFT_MARGIN, y, style)
            return
        natural_width = estimate_width(text, style.font_key, style.size)
        extra_space = max(0.0, (CONTENT_WIDTH - natural_width) / spaces)
        r, g, b = style.color
        font_name = FONT_MAP[style.font_key]
        escaped = escape_pdf_text(text)
        self.current_ops.append(
            "BT "
            f"/{font_name} {style.size} Tf "
            f"{r:.3f} {g:.3f} {b:.3f} rg "
            f"{extra_space:.3f} Tw "
            f"1 0 0 1 {LEFT_MARGIN:.2f} {y:.2f} Tm "
            f"({escaped}) Tj ET"
        )

    def add_block(self, text: str, style: TextStyle, space_after: int = 12) -> None:
        lines = wrap_text(text, style.font_key, style.size, CONTENT_WIDTH)
        last_index = len(lines) - 1
        for index, line in enumerate(lines):
            is_last_line = index == last_index
            required_space = style.leading + (space_after if is_last_line else 0)
            self.ensure_space(required_space)
            if style.justify and index != last_index:
                self.write_justified_line(line, self.cursor_y, style)
            else:
                self.write_line(line, LEFT_MARGIN, self.cursor_y, style)
            self.cursor_y -= style.leading
        self.cursor_y -= space_after

    def add_heading(self, text: str, size: int, space_after: int = 10) -> None:
        style = TextStyle("sans-bold", size, int(size * 1.2), (0.05, 0.05, 0.05))
        self.add_block(text, style, space_after=space_after)

    def add_inline_chapter_heading(self, text: str, timestamp: float) -> None:
        self.cursor_y -= 6
        style = TextStyle("sans-bold", 13, 17, (0.10, 0.10, 0.10))
        self.add_block(text, style, space_after=8)

    def add_meta(self, text: str) -> None:
        style = TextStyle("sans", 11, 15, (0.35, 0.35, 0.35))
        self.add_block(text, style, space_after=6)

    def add_paragraph(self, text: str) -> None:
        style = TextStyle("serif", 12, 18, (0.08, 0.08, 0.08), justify=True)
        self.add_block(text, style, space_after=10)

    def add_marker(self, text: str) -> None:
        style = TextStyle("sans-bold", 10, 14, (0.48, 0.15, 0.12))
        self.ensure_space(30)
        self.cursor_y -= 4
        self.write_line(text, LEFT_MARGIN, self.cursor_y, style)
        self.cursor_y -= 20

    def add_chapter_list(self, chapters: list[dict]) -> None:
        style = TextStyle("sans", 11, 15, (0.08, 0.08, 0.08))
        for index, chapter in enumerate(chapters, start=1):
            line = f"{index}. {format_time(chapter['start_time'])}  {chapter['title']}"
            self.add_block(line, style, space_after=2)
        self.cursor_y -= 8

    def finalize(self) -> bytes:
        if self.current_ops:
            self.close_page()

        objects: list[bytes] = []

        def add_object(payload: bytes) -> int:
            objects.append(payload)
            return len(objects)

        font_helvetica = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        font_bold = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        font_times = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>")

        page_ids = []
        for ops in self.pages:
            stream = "\n".join(ops).encode("utf-8")
            content_id = add_object(
                b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
            )
            page_payload = (
                f"<< /Type /Page /Parent PAGES_ID 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 {font_helvetica} 0 R /F2 {font_bold} 0 R /F3 {font_times} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("utf-8")
            page_ids.append(add_object(page_payload))

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        pages_id = add_object(
            f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("utf-8")
        )

        for index, payload in enumerate(objects):
            if b"PAGES_ID" in payload:
                objects[index] = payload.replace(b"PAGES_ID", str(pages_id).encode("ascii"))

        catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("utf-8"))

        result = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for index, payload in enumerate(objects, start=1):
            offsets.append(len(result))
            result.extend(f"{index} 0 obj\n".encode("ascii"))
            result.extend(payload)
            result.extend(b"\nendobj\n")

        xref_offset = len(result)
        result.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
        result.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            result.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        result.extend(
            (
                f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
                f"startxref\n{xref_offset}\n%%EOF\n"
            ).encode("ascii")
        )
        return bytes(result)


def build_meta(args: argparse.Namespace) -> list[str]:
    lines = [args.date]
    if args.channel:
        lines.append(args.channel)
    if args.source_url:
        lines.append(args.source_url)
    return lines


def chapter_key(seconds: float) -> int:
    return int(round(seconds * 10))


def chapter_lookup(chapters: list[dict]) -> dict[int, list[dict]]:
    lookup: dict[int, list[dict]] = {}
    for chapter in chapters:
        lookup.setdefault(chapter_key(chapter["start_time"]), []).append(chapter)
    return lookup


def render_pdf(args: argparse.Namespace) -> Path:
    transcript_blocks = load_transcript(args.transcript)
    transcript_metadata = load_transcript_metadata(args.transcript_metadata_json)
    summary_blocks = load_summary(args.summary_file)
    chapters = filter_close_chapters(load_chapters(args.chapters_json))
    chapters_by_key = chapter_lookup(chapters)
    rendered_chapter_keys: set[int] = set()

    output = Path(args.output) if args.output else Path.cwd() / f"{slugify(args.title)}.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)

    doc = PDFDocument()
    doc.add_heading(args.title, 24, space_after=8)

    for line in build_meta(args):
        doc.add_meta(line)

    doc.cursor_y -= 8
    doc.draw_rule()
    doc.cursor_y -= 24

    if summary_blocks:
        doc.add_heading("Summary", 15, space_after=6)
        for block in summary_blocks:
            doc.add_paragraph(block)
        doc.cursor_y -= 4

    if chapters:
        doc.add_heading("Chapters", 15, space_after=6)
        doc.add_chapter_list(chapters)

    doc.add_heading("Transcript", 15, space_after=6)
    if transcript_metadata:
        for block in transcript_metadata:
            start = block["start"]
            for chapter in chapters:
                key = chapter_key(chapter["start_time"])
                if key in rendered_chapter_keys:
                    continue
                if start >= chapter["start_time"]:
                    doc.add_inline_chapter_heading(chapter["title"], chapter["start_time"])
                    rendered_chapter_keys.add(key)
            if block["type"] == "marker":
                doc.add_marker(block["text"])
            else:
                doc.add_paragraph(block["text"])
    else:
        for block in transcript_blocks:
            if is_marker(block):
                doc.add_marker(block)
            else:
                doc.add_paragraph(block)

    output.write_bytes(doc.finalize())
    return output


def main() -> None:
    args = parse_args()
    output = render_pdf(args)
    print(output)


if __name__ == "__main__":
    main()
