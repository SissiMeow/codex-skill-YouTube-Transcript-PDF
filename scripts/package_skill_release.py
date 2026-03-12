#!/usr/bin/env python3
"""Build a clean distribution zip for the youtube-transcript skill."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


INCLUDED_PATHS = [
    "SKILL.md",
    "LICENSE",
    "agents/openai.yaml",
]

INCLUDED_DIRS = [
    "scripts",
]

EXCLUDED_FILE_NAMES = {
    "README.md",
}

EXCLUDED_DIR_NAMES = {
    ".git",
    "__pycache__",
    "tests",
    "dist",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package the youtube-transcript skill into a clean release zip.",
    )
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to the youtube-transcript skill root.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Zip output path. Defaults to <skill-root>/dist/youtube-transcript.zip",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include tests/ fixtures in the zip for debugging or local sharing.",
    )
    return parser.parse_args()


def should_skip(path: Path, *, include_tests: bool) -> bool:
    if path.name in EXCLUDED_FILE_NAMES:
        return True
    for part in path.parts:
        if part in EXCLUDED_DIR_NAMES:
            if part == "tests" and include_tests:
                continue
            return True
    return False


def iter_release_files(skill_root: Path, include_tests: bool):
    for relative in INCLUDED_PATHS:
        path = skill_root / relative
        if path.exists() and not should_skip(path.relative_to(skill_root), include_tests=include_tests):
            yield path

    for relative in INCLUDED_DIRS:
        directory = skill_root / relative
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(skill_root)
            if should_skip(rel, include_tests=include_tests):
                continue
            yield path

    if include_tests:
        tests_dir = skill_root / "tests"
        if tests_dir.exists():
            for path in sorted(tests_dir.rglob("*")):
                if path.is_dir():
                    continue
                rel = path.relative_to(skill_root)
                if should_skip(rel, include_tests=include_tests):
                    continue
                yield path


def main() -> None:
    args = parse_args()
    skill_root = args.skill_root.resolve()
    output = args.output.resolve() if args.output else skill_root / "dist" / "youtube-transcript.zip"
    output.parent.mkdir(parents=True, exist_ok=True)

    release_root = skill_root.name
    seen: set[Path] = set()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in iter_release_files(skill_root, include_tests=args.include_tests):
            rel = path.relative_to(skill_root)
            if rel in seen:
                continue
            seen.add(rel)
            archive.write(path, arcname=str(Path(release_root) / rel))

    print(output)


if __name__ == "__main__":
    main()
