#!/usr/bin/env python3
"""Transcribe audio into segment JSON using faster-whisper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from faster_whisper import WhisperModel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ASR with faster-whisper and write segment JSON.",
    )
    parser.add_argument("audio", help="Path to the input audio file")
    parser.add_argument("--output", required=True, help="Path to write JSON segments")
    parser.add_argument("--language", help="Optional language code")
    parser.add_argument(
        "--model",
        default="small",
        help="Whisper model size or repo id. Default: small",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Execution device. Default: cpu",
    )
    parser.add_argument(
        "--compute-type",
        default="int8",
        help="CTranslate2 compute type. Default: int8",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=1,
        help="Beam size for decoding. Default: 1",
    )
    parser.add_argument(
        "--vad-filter",
        action="store_true",
        help="Enable voice activity detection filtering.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    segments, info = model.transcribe(
        args.audio,
        language=args.language,
        beam_size=args.beam_size,
        vad_filter=args.vad_filter,
    )

    payload = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        payload.append(
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": text,
            }
        )

    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    info_payload = {
        "language": getattr(info, "language", None),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
        "duration_after_vad": getattr(info, "duration_after_vad", None),
    }
    info_path = Path(args.output).with_suffix(".info.json")
    info_path.write_text(json.dumps(info_payload, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
