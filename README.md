# YouTube Transcript Skill

Turn a YouTube video into a readable longform transcript package instead of a raw subtitle dump.

This Codex skill extracts a transcript from a YouTube URL, prefers native captions when available, falls back to ASR when needed, and assembles the result into a polished article-style deliverable. It is designed for workflows that need more than plain text: title, publication date, source metadata, summary, chapter breakdown, and a final PDF saved in the current project folder.

## What This Skill Does

- Accepts a YouTube URL as input
- Checks for native or auto-generated captions first
- Falls back to speech-to-text only when captions are missing or poor quality
- Normalizes timed segments into readable paragraphs
- Produces a summary and chapter list
- Renders a polished PDF transcript in the working directory
- Keeps the source language by default
- Adds Chinese translation only when explicitly requested

## Typical Use Cases

Use this skill when you want to:

- turn a YouTube video into a readable article
- save a podcast or talk as a well-formatted PDF
- extract a transcript with metadata and chapter structure
- avoid messy subtitle fragments in the final output
- create a shareable reading artifact from long video content

## Output

Unless the user asks for something else, the skill aims to produce:

1. Video title
2. Publication date
3. Channel or source metadata
4. Short summary
5. Chapter breakdown
6. Readable transcript body
7. PDF file saved in the current project folder

Example output path:

```text
./cult-leaders-have-terrible-pitches.pdf
```

## Workflow

1. Confirm the input is a YouTube URL.
2. Inspect subtitle availability and metadata.
3. Prefer manual captions over auto-generated captions.
4. Use ASR only if captions are unavailable or materially incomplete.
5. Convert timed caption segments into prose-like paragraphs.
6. Generate a concise summary and chapter list.
7. Render the final transcript package as a polished PDF.

## Included Files

- `SKILL.md`: main skill instructions and quality bar
- `scripts/assemble_transcript.py`: converts timed segments into readable transcript text
- `scripts/render_blog_pdf.py`: renders a polished PDF from transcript inputs
- `agents/openai.yaml`: agent configuration used by the skill

## Example Script Usage

```bash
python scripts/assemble_transcript.py segments.json --output transcript.txt
python scripts/render_blog_pdf.py \
  --title "Cult Leaders Have Terrible Pitches" \
  --date "September 16, 2025" \
  --channel "The Knowledge Project Podcast" \
  --summary-file summary.txt \
  --chapters-json chapters.json \
  --transcript transcript.txt \
  --output ./cult-leaders-have-terrible-pitches.pdf
```

## Quality Principles

This skill is built around a simple standard: the final deliverable should read like an article, not like exported subtitles.

That means it tries to:

- merge fragmented caption lines into paragraphs
- remove repeated overlaps from subtitle windows
- avoid excessive timestamp noise
- preserve the original language unless translation is requested
- keep the final PDF readable and visually structured

## Notes

- Caption-first extraction is preferred because it is faster and cheaper than ASR.
- Translation is not automatic.
- Final quality depends on the quality of the available captions or transcription source.

## License

This repository includes a `LICENSE` file. Review it before reusing or redistributing the skill.
