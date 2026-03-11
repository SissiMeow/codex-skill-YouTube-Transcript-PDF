---
name: youtube-transcript
description: Extract transcripts from YouTube videos and turn them into polished article-style deliverables. Use when a user provides a YouTube URL and wants native-caption extraction, ASR fallback, a readable transcript with title/date/chapter information, OpenAI-blog-inspired longform formatting, a summary, chapter breakdown, or a final PDF saved inside the current project folder. Add Chinese translation only when explicitly requested.
---

# YouTube Transcript

## Overview

Turn a YouTube URL into a polished reading artifact, not a raw dump of captions. Prefer YouTube's native captions first, then fall back to speech-to-text only when captions are missing, unusable, or materially incomplete.

## Workflow

1. Confirm the input is a YouTube URL.
2. Inspect whether native subtitles or auto-generated captions are available.
3. Extract captions when possible because they are faster and cheaper than ASR.
4. Fall back to speech-to-text only if caption extraction fails or the result is materially incomplete.
5. Gather metadata: title, publication date, channel, URL, and source chapters when available.
6. Normalize the transcript into readable paragraphs instead of caption fragments.
7. Build a document with title, date, source metadata, summary, chapter list, and transcript body.
8. Save the final deliverable as a PDF inside the current project folder.
9. Add Chinese translation only when the prompt explicitly asks for it.

## Source Selection

### Caption-first path

Prefer this path when native subtitles or auto-generated YouTube captions exist.

- Fetch metadata and subtitle availability first.
- Download the best subtitle track in the original language.
- If both manual and auto captions exist, prefer manual captions.
- If the user does not specify a language, preserve the video's original caption language.
- If captions are partial, badly desynchronized, or omit large spoken sections, switch to ASR.

Useful tools if available in the environment:

- `yt-dlp` for metadata and subtitle extraction
- Any local caption downloader already present in the repo or machine

### ASR fallback path

Use ASR only when caption extraction is unavailable or not good enough.

- Download or access the YouTube audio.
- Run transcription in the source language when known.
- Preserve the original language in the transcript.
- Do not translate by default.
- Use the transcript as the source of truth for the final readable article and PDF.

Common options if available:

- Local Whisper / faster-whisper
- Hosted transcription API

## Output Contract

Unless the user asks otherwise, produce a polished PDF in the current project folder containing:

1. Title
2. Publication date
3. Source line with channel or origin
4. Summary or dek
5. Chapter list near the top
6. Readable transcript body in the original language
7. Coarse timestamp markers only when useful, such as every 20 minutes

Do not return a giant unstructured block of caption text as the main deliverable.

## Formatting Rules

Model the reading experience on OpenAI longform posts such as the Harness Engineering article: generous whitespace, strong title hierarchy, compact metadata, clear section breaks, and readable paragraph widths.

- Start with an overline or section label such as `YouTube Transcript`.
- Put the title first.
- Put the publication date and source metadata directly under the title.
- Put the chapter list near the top of the document.
- Keep paragraphs short and readable.
- Justify body paragraphs so the text block width matches the divider line width.
- Merge caption fragments into prose-like paragraphs.
- Remove repeated overlaps caused by subtitle segmentation.
- Remove obvious noise such as repeated arrows or standalone music markers unless editorially useful.
- Do not invent speaker names.
- Do not emit dense timestamp noise.
- Insert 20-minute markers only as coarse navigation aids.
- If the video is shorter than 20 minutes, omit markers entirely.
- Reserve a footer whitespace band on every page and separate it from body text with a grey horizontal rule.

## Readability Heuristics

When normalizing captions:

- Deduplicate exact repeats from overlapping subtitle windows.
- Split long text into paragraphs by time gaps, sentence endings, and paragraph length.
- Prefer paragraph lengths that feel like essay prose, not subtitle streams.
- Preserve punctuation if the source provides it.
- If source punctuation is poor, add only the minimum punctuation needed for readability.

## Summary And Chapters

After building the transcript, create:

- A concise summary focused on the video's main argument or takeaways
- A chapter list with short headings

If the source data already contains reliable chapter metadata, reuse it. Otherwise infer chapters from topic shifts in the transcript.

## Output Location

Save the final PDF inside the current project folder unless the user asks for another path. Prefer a slugged filename derived from the video title.

Example:

```text
./cult-leaders-have-terrible-pitches.pdf
```

## Helper Scripts

Use `scripts/assemble_transcript.py` to turn timed segments into readable transcript prose with coarse markers.

Use `scripts/render_blog_pdf.py` to turn metadata, summary, chapters, and transcript text into a polished PDF without external PDF dependencies.

Typical flow:

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

## Quality Checks

Before returning the result, verify:

- The transcript language matches the source content unless translation was explicitly requested
- The transcript is materially complete
- The chapter list is coherent
- The document has title, date, and source metadata
- The PDF was written successfully inside the project folder
- Body text is justified and aligned to the same width as the divider rules
- No page lets body text cross into the footer whitespace band
- The final document is readable as an article, not as raw subtitles

If extraction quality is poor, say so briefly and state whether the weakness comes from source captions or ASR.

## Response Pattern

When handling a user request with this skill:

1. State whether the transcript came from native captions or ASR fallback.
2. Save the final PDF in the project folder.
3. Return the PDF path.
4. Return the summary.
5. Return the chapter breakdown.
6. Add translation only if explicitly requested.
