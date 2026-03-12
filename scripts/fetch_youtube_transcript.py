#!/usr/bin/env python3
"""Fetch YouTube metadata and transcript data through one deterministic entrypoint."""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse


YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})(?:\s+.*)?$"
)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[.!?;:,]")
YT_DLP_BASE_ARGS = [
    "yt-dlp",
    "--ignore-config",
    "--no-warnings",
]
YT_DLP_METADATA_FORMAT = "sb0"


class TranscriptFetchError(RuntimeError):
    """Raised when transcript extraction cannot continue safely."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch YouTube metadata, captions, and optional ASR fallback outputs.",
    )
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for metadata.json, segments.json, chapters.json, and report.json",
    )
    parser.add_argument(
        "--language",
        help="Preferred subtitle language code such as en or es. Defaults to the original language when known.",
    )
    parser.add_argument(
        "--prefer-auto-captions",
        action="store_true",
        help="Prefer automatic captions over manual captions when both exist.",
    )
    parser.add_argument(
        "--subtitle-format",
        default="vtt",
        choices=["vtt"],
        help="Subtitle format requested from yt-dlp. Default: vtt",
    )
    parser.add_argument(
        "--asr-command",
        help=(
            "Optional shell command for ASR fallback. It must create segments JSON at {segments}. "
            "Available placeholders: {audio}, {segments}, {metadata}, {output_dir}."
        ),
    )
    parser.add_argument(
        "--cookies-from-browser",
        help="Optional browser name passed to yt-dlp, such as Safari or Chrome.",
    )
    parser.add_argument(
        "--minimum-coverage-ratio",
        type=float,
        default=0.60,
        help="Fail the caption path when transcript coverage falls below this ratio. Default: 0.60",
    )
    parser.add_argument(
        "--minimum-segments",
        type=int,
        default=10,
        help="Fail the caption path when fewer than this many segments are extracted. Default: 10",
    )
    parser.add_argument(
        "--minimum-punctuation-density",
        type=float,
        default=0.003,
        help="Warn when punctuation density falls below this threshold. Default: 0.003",
    )
    parser.add_argument(
        "--asr-model",
        default="small",
        help="Model name used by the bundled faster-whisper fallback. Default: small",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        run(args)
    except TranscriptFetchError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


def run(args: argparse.Namespace) -> None:
    ensure_youtube_url(args.url)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_command("yt-dlp")

    info = fetch_info(args.url, cookies_from_browser=args.cookies_from_browser)
    metadata = build_metadata(info, args.url)
    chapters = build_chapters(info)
    write_json(output_dir / "metadata.json", metadata)
    write_json(output_dir / "chapters.json", chapters)

    report = {
        "url": args.url,
        "video_id": metadata.get("video_id"),
        "title": metadata.get("title"),
        "source_type": None,
        "selected_language": None,
        "warnings": [],
        "quality": {},
    }

    caption_result = try_caption_path(
        args=args,
        info=info,
        metadata=metadata,
    )

    if caption_result["usable"]:
        write_json(output_dir / "segments.json", caption_result["segments"])
        report["source_type"] = caption_result["source_type"]
        report["selected_language"] = caption_result["language"]
        report["warnings"].extend(caption_result["warnings"])
        report["quality"] = caption_result["quality"]
        write_json(output_dir / "report.json", report)
        return

    report["warnings"].extend(caption_result["warnings"])

    if not args.asr_command:
        args.asr_command = default_asr_command(args)
        if not args.asr_command:
            write_json(output_dir / "report.json", report)
            raise TranscriptFetchError(
                "Caption extraction was unavailable or too incomplete and no ASR fallback was configured."
            )

    asr_result = run_asr_fallback(
        args=args,
        output_dir=output_dir,
        metadata=metadata,
    )
    write_json(output_dir / "segments.json", asr_result["segments"])
    report["source_type"] = "asr"
    report["selected_language"] = asr_result["language"]
    report["warnings"].extend(asr_result["warnings"])
    report["quality"] = asr_result["quality"]
    write_json(output_dir / "report.json", report)


def ensure_youtube_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in YOUTUBE_HOSTS:
        raise TranscriptFetchError(f"Input is not a supported YouTube URL: {url}")
    if host.endswith("youtube.com") and parsed.path == "/watch":
        query = parse_qs(parsed.query)
        if not query.get("v"):
            raise TranscriptFetchError(f"YouTube watch URL is missing a video id: {url}")
    if host.endswith("youtu.be") and not parsed.path.strip("/"):
        raise TranscriptFetchError(f"Short YouTube URL is missing a video id: {url}")


def ensure_command(command: str) -> None:
    if shutil.which(command):
        return
    raise TranscriptFetchError(f"Required dependency is unavailable: {command}")


def run_command(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip() or "unknown error"
        raise TranscriptFetchError(f"Command failed: {' '.join(command)}\n{stderr}") from exc


def fetch_info(url: str, cookies_from_browser: str | None = None) -> dict:
    result = run_command(
        yt_dlp_command(
            ["-f", YT_DLP_METADATA_FORMAT, "--dump-single-json", "--skip-download", url],
            cookies_from_browser=cookies_from_browser,
        )
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TranscriptFetchError("yt-dlp returned invalid metadata JSON.") from exc
    if not isinstance(data, dict):
        raise TranscriptFetchError("yt-dlp metadata response was not an object.")
    return data


def build_metadata(info: dict, url: str) -> dict:
    return {
        "video_id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id"),
        "upload_date": info.get("upload_date"),
        "release_date": info.get("release_date"),
        "language": info.get("language"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or url,
        "description": info.get("description"),
    }


def build_chapters(info: dict) -> list[dict]:
    chapters = []
    for chapter in info.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        title = str(chapter.get("title", "")).strip()
        if not title:
            continue
        chapters.append(
            {
                "title": title,
                "start_time": float(chapter.get("start_time", 0) or 0),
                "end_time": float(chapter.get("end_time", 0) or 0),
            }
        )
    return chapters


def try_caption_path(
    *,
    args: argparse.Namespace,
    info: dict,
    metadata: dict,
) -> dict:
    subtitles = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    chosen = choose_caption_track(
        manual=subtitles,
        automatic=automatic,
        requested_language=args.language,
        original_language=metadata.get("language"),
        prefer_auto=args.prefer_auto_captions,
    )
    if not chosen:
        return {
            "usable": False,
            "source_type": None,
            "language": None,
            "segments": [],
            "warnings": ["No usable caption track was discovered."],
            "quality": {},
        }

    with TemporaryDirectory(prefix="youtube-transcript-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        subtitle_path = download_caption_track(
            url=metadata["webpage_url"],
            temp_dir=temp_dir,
            language=chosen["language"],
            source_type=chosen["source_type"],
            subtitle_format=args.subtitle_format,
            cookies_from_browser=args.cookies_from_browser,
        )
        segments = parse_vtt(subtitle_path)

    quality = assess_segments(
        segments=segments,
        duration_seconds=float(metadata.get("duration") or 0),
        minimum_punctuation_density=args.minimum_punctuation_density,
    )
    warnings = list(quality["warnings"])
    usable = bool(segments) and quality["coverage_ratio"] >= args.minimum_coverage_ratio
    usable = usable and quality["segment_count"] >= args.minimum_segments

    if not usable:
        warnings.append(
            "Caption transcript was extracted but rejected because coverage or segment count was too low."
        )

    return {
        "usable": usable,
        "source_type": chosen["source_type"],
        "language": chosen["language"],
        "segments": segments,
        "warnings": warnings,
        "quality": quality,
    }


def choose_caption_track(
    *,
    manual: dict,
    automatic: dict,
    requested_language: str | None,
    original_language: str | None,
    prefer_auto: bool,
) -> dict | None:
    sources: list[tuple[str, dict]]
    if prefer_auto:
        sources = [("auto", automatic), ("caption", manual)]
    else:
        sources = [("caption", manual), ("auto", automatic)]

    preferred = [requested_language, original_language]
    for source_type, tracks in sources:
        language = choose_language(tracks, preferred)
        if language:
            return {"source_type": source_type, "language": language}
    return None


def choose_language(tracks: dict, preferred: list[str | None]) -> str | None:
    if not isinstance(tracks, dict) or not tracks:
        return None
    available = list(tracks.keys())
    normalized = {normalize_language(code): code for code in available}
    for candidate in preferred:
        if not candidate:
            continue
        if candidate in tracks:
            return candidate
        folded = normalize_language(candidate)
        if folded in normalized:
            return normalized[folded]
        prefix_match = next((code for code in available if normalize_language(code).startswith(folded)), None)
        if prefix_match:
            return prefix_match
    orig_match = next((code for code in available if normalize_language(code).endswith("-orig")), None)
    if orig_match:
        return orig_match
    english_match = next((code for code in available if normalize_language(code) in {"en", "en-us", "en-gb"}), None)
    if english_match:
        return english_match
    simple_match = next((code for code in available if "-" not in normalize_language(code) or normalize_language(code).count("-") == 1 and normalize_language(code).endswith(("-hans", "-hant"))), None)
    if simple_match:
        return simple_match
    return available[0]


def normalize_language(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def download_caption_track(
    *,
    url: str,
    temp_dir: Path,
    language: str,
    source_type: str,
    subtitle_format: str,
    cookies_from_browser: str | None,
) -> Path:
    output_template = temp_dir / "captions.%(ext)s"
    command = yt_dlp_command(
        [
            "-f",
            YT_DLP_METADATA_FORMAT,
            "--skip-download",
            "--sub-langs",
            language,
            "--sub-format",
            subtitle_format,
            "--output",
            str(output_template),
        ],
        cookies_from_browser=cookies_from_browser,
    )
    if source_type == "auto":
        command.append("--write-auto-subs")
    else:
        command.append("--write-subs")
    command.append(url)
    run_command(command)

    candidates = sorted(temp_dir.glob("captions*"))
    subtitle_path = next((path for path in candidates if path.suffix.lower() == f".{subtitle_format.lower()}"), None)
    if subtitle_path is None:
        subtitle_path = next((path for path in candidates if path.suffix.lower() == ".vtt"), None)
    if subtitle_path is None:
        raise TranscriptFetchError(f"yt-dlp did not write a {subtitle_format} subtitle file for language {language}.")
    return subtitle_path


def parse_vtt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    segments = []
    for block in blocks:
        lines = [line.strip("\ufeff ") for line in block.split("\n") if line.strip()]
        if not lines or lines[0] == "WEBVTT":
            continue
        if lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue

        index = 0
        if index < len(lines) and TIMESTAMP_RE.fullmatch(lines[index]) is None and "-->" not in lines[index]:
            index += 1
        if index >= len(lines):
            continue

        match = TIMESTAMP_RE.fullmatch(lines[index])
        if not match:
            continue
        cue_lines = lines[index + 1 :]
        cleaned_lines = [clean_caption_text(line) for line in cue_lines]
        cleaned_lines = [line for line in cleaned_lines if line]
        if not cleaned_lines:
            continue
        segments.append(
            {
                "start": timestamp_to_seconds(match.group("start")),
                "end": timestamp_to_seconds(match.group("end")),
                "text": " ".join(cleaned_lines),
            }
        )
    return collapse_repeated_segments(segments)


def clean_caption_text(text: str) -> str:
    text = html.unescape(text)
    text = TAG_RE.sub("", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace(">>", " ")
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text


def timestamp_to_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, milliseconds = rest.split(".")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(milliseconds) / 1000
    )


def collapse_repeated_segments(segments: list[dict]) -> list[dict]:
    collapsed: list[dict] = []
    previous_text = ""
    for segment in segments:
        text = segment["text"]
        if not text:
            continue
        if text == previous_text:
            continue
        if previous_text and (
            text.startswith(previous_text)
            or previous_text.startswith(text)
            or suffix_prefix_word_overlap(previous_text, text) >= 3
        ):
            merged = merge_overlap(previous_text, text)
            collapsed[-1]["text"] = merged
            collapsed[-1]["end"] = max(
                float(collapsed[-1].get("end", collapsed[-1]["start"])),
                float(segment.get("end", segment["start"])),
            )
            previous_text = merged
            continue
        collapsed.append(segment)
        previous_text = text
    return collapsed


def suffix_prefix_overlap(left: str, right: str) -> int:
    max_len = min(len(left), len(right))
    for size in range(max_len, 0, -1):
        if left[-size:] == right[:size]:
            return size
    return 0


def suffix_prefix_word_overlap(left: str, right: str) -> int:
    left_words = left.split()
    right_words = right.split()
    max_len = min(len(left_words), len(right_words))
    for size in range(max_len, 2, -1):
        if [word.lower() for word in left_words[-size:]] == [word.lower() for word in right_words[:size]]:
            return size
    return 0


def merge_overlap(left: str, right: str) -> str:
    if right.startswith(left):
        return right
    if left.startswith(right):
        return left
    word_overlap = suffix_prefix_word_overlap(left, right)
    if word_overlap:
        return " ".join(left.split() + right.split()[word_overlap:])
    overlap = suffix_prefix_overlap(left, right)
    if overlap >= 24:
        return left + right[overlap:]
    return right


def assess_segments(
    *,
    segments: list[dict],
    duration_seconds: float,
    minimum_punctuation_density: float,
) -> dict:
    full_text = " ".join(segment["text"] for segment in segments)
    char_count = len(full_text)
    punct_count = len(PUNCT_RE.findall(full_text))
    punctuation_density = (punct_count / char_count) if char_count else 0.0
    last_end = max((float(segment.get("end", segment["start"])) for segment in segments), default=0.0)
    coverage_ratio = (last_end / duration_seconds) if duration_seconds else 1.0
    repeated_ratio = repeated_text_ratio(segments)
    warnings = []
    if punctuation_density < minimum_punctuation_density:
        warnings.append("Transcript punctuation density is low; source captions may be noisy.")
    if coverage_ratio < 0.75:
        warnings.append("Transcript coverage appears incomplete relative to the video duration.")
    if repeated_ratio > 0.10:
        warnings.append("Transcript still contains a notable amount of repeated text.")
    return {
        "segment_count": len(segments),
        "character_count": char_count,
        "punctuation_density": round(punctuation_density, 6),
        "coverage_ratio": round(coverage_ratio, 4),
        "repeated_text_ratio": round(repeated_ratio, 4),
        "warnings": warnings,
    }


def repeated_text_ratio(segments: list[dict]) -> float:
    if not segments:
        return 0.0
    repeats = 0
    previous = ""
    for segment in segments:
        text = segment["text"]
        if text == previous:
            repeats += 1
        previous = text
    return repeats / len(segments)


def run_asr_fallback(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    metadata: dict,
) -> dict:
    with TemporaryDirectory(prefix="youtube-audio-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        audio_path = download_audio(
            metadata["webpage_url"],
            temp_dir,
            cookies_from_browser=args.cookies_from_browser,
        )
        segments_path = output_dir / "segments.json"
        command = args.asr_command.format(
            audio=shlex.quote(str(audio_path)),
            segments=shlex.quote(str(segments_path)),
            metadata=shlex.quote(str(output_dir / "metadata.json")),
            output_dir=shlex.quote(str(output_dir)),
            language=shlex.quote(str(args.language or "")),
            asr_model=shlex.quote(str(args.asr_model)),
        )
        try:
            subprocess.run(command, shell=True, text=True, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() or exc.stdout.strip() or "unknown error"
            raise TranscriptFetchError(f"ASR fallback command failed.\n{stderr}") from exc

    try:
        segments = json.loads(segments_path.read_text())
    except FileNotFoundError as exc:
        raise TranscriptFetchError(
            "ASR fallback completed without writing the expected segments.json output."
        ) from exc
    except json.JSONDecodeError as exc:
        raise TranscriptFetchError("ASR fallback wrote invalid JSON to segments.json.") from exc

    if not isinstance(segments, list):
        raise TranscriptFetchError("ASR fallback must write a JSON list of transcript segments.")
    normalized = []
    for item in segments:
        if not isinstance(item, dict):
            continue
        text = clean_caption_text(str(item.get("text", "")))
        if not text:
            continue
        normalized.append(
            {
                "start": float(item.get("start", 0) or 0),
                "end": float(item.get("end", item.get("start", 0)) or 0),
                "text": text,
            }
        )
    quality = assess_segments(
        segments=normalized,
        duration_seconds=float(metadata.get("duration") or 0),
        minimum_punctuation_density=args.minimum_punctuation_density,
    )
    warnings = list(quality["warnings"])
    warnings.append("ASR fallback was used because captions were unavailable or insufficient.")
    return {
        "language": args.language or metadata.get("language"),
        "segments": normalized,
        "warnings": warnings,
        "quality": quality,
    }


def download_audio(url: str, temp_dir: Path, cookies_from_browser: str | None = None) -> Path:
    output_template = temp_dir / "audio.%(ext)s"
    run_command(
        yt_dlp_command(
            ["-f", "bestaudio/best", "--output", str(output_template), url],
            cookies_from_browser=cookies_from_browser,
        )
    )
    candidates = sorted(path for path in temp_dir.glob("audio.*") if path.is_file())
    if not candidates:
        raise TranscriptFetchError("yt-dlp did not download an audio file for ASR fallback.")
    return candidates[0]


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def yt_dlp_command(extra_args: list[str], cookies_from_browser: str | None = None) -> list[str]:
    command = [*YT_DLP_BASE_ARGS]
    if cookies_from_browser:
        command.extend(["--cookies-from-browser", cookies_from_browser])
    command.extend(extra_args)
    return command


def default_asr_command(args: argparse.Namespace) -> str | None:
    script_path = Path(__file__).resolve().parent / "asr_faster_whisper.py"
    if not script_path.exists():
        return None
    if importlib.util.find_spec("faster_whisper") is None:
        return None
    command = (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))} "
        f"{{audio}} --output {{segments}} --model {{asr_model}} --device cpu --compute-type int8 --beam-size 1 --vad-filter"
    )
    if args.language:
        command += " --language {language}"
    return command


if __name__ == "__main__":
    main()
