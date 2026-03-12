---
name: youtube-transcript
description: Extract transcripts from YouTube videos and turn them into polished article-style deliverables. Use when a user provides a YouTube URL and asks for transcript extraction, subtitle capture, readable longform transcript cleanup, video summarization from the transcript, chapter reconstruction, or a final PDF saved in the current project folder. Preserve the source language by default and add Chinese translation only when explicitly requested. Do not use for casual discussion about a YouTube video unless the user asks for transcript extraction, summarization, or document creation.
---

# YouTube Transcript

## Overview

Turn a YouTube URL into a polished reading artifact, not a raw dump of captions. Prefer YouTube's native captions first, then fall back to speech-to-text only when captions are missing, unusable, or materially incomplete.

## Workflow

1. Confirm the input is a YouTube URL.
2. Gather metadata and inspect whether native subtitles or auto-generated captions are available.
3. Prefer caption extraction because it is faster and cheaper than ASR.
4. Fall back to speech-to-text only if caption extraction fails or the result is materially incomplete.
5. Gather metadata: title, publication date, channel, URL, and source chapters when available.
6. Normalize the transcript into readable paragraphs instead of caption fragments.
7. Build a document with title, date, source metadata, summary, chapter list, and transcript body.
8. Save the final deliverable as a PDF inside the current project folder.
9. Add Chinese translation only when the prompt explicitly asks for it.

## Environment Contract

Expect the environment to provide:

- `python3`
- Network access to read the YouTube page and any transcript source
- `yt-dlp` for metadata and subtitle extraction on the caption-first path
- Either a local Whisper-compatible ASR tool or a hosted transcription API for fallback
- The bundled scripts in `scripts/`

If any required capability is missing, say exactly which dependency is unavailable and stop before claiming the transcript is complete.

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
- The canonical extraction wrapper in `scripts/` when present

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

## Failure Policy

Stop and explain the failure if any of the following is true:

- The input is not a valid YouTube URL
- Metadata cannot be fetched
- Captions are unavailable and no ASR fallback is available
- Audio download fails for the ASR path
- The transcript is too incomplete to support a trustworthy summary

Continue with a warning when work is possible but quality is limited:

- Captions exist but appear partial, noisy, or desynchronized
- ASR finishes but punctuation or speaker boundaries are weak
- Chapter boundaries must be inferred from noisy transcript text

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
- Keep page 1 free of the repeated page-header label and top divider block.
- On page 2 and later, place the top divider so its distance to the page top matches the bottom divider's distance to the page bottom.
- Put the `Sissi Skill - YouTube Transcript to PDF` page label just above that top divider on page 2 and later.
- Put the publication date and source metadata directly under the title.
- Put the chapter list near the top of the document.
- Reinsert chapter headings inside the transcript body at their corresponding locations when chapter metadata exists.
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
- Let body text run close to the footer divider so the final line sits roughly one line above it without overlap.

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

## Examples

Example 1: Podcast transcript package

- User says: "Turn this YouTube interview into a clean PDF transcript."
- Actions:
  1. Fetch metadata and caption availability.
  2. Prefer manual captions when available.
  3. Normalize transcript paragraphs.
  4. Generate summary and chapter list.
  5. Render PDF in the current project folder.
- Result: Article-style transcript PDF plus summary and chapter breakdown.

Example 2: Summary plus transcript from a keynote

- User says: "Extract the transcript from this keynote and summarize each section."
- Actions:
  1. Extract captions or use ASR fallback.
  2. Reuse source chapters when present, otherwise infer them.
  3. Build a concise summary aligned to the chapter structure.
  4. Save the final PDF and return the summary in chat.
- Result: Usable reading artifact instead of raw subtitle text.

Example 3: Preserve source language

- User says: "Make a readable transcript from this Spanish YouTube talk."
- Actions:
  1. Preserve the Spanish transcript.
  2. Do not translate unless explicitly asked.
  3. Flag source-quality issues if captions are weak.
- Result: Spanish transcript package with honest quality notes.

Example 4: Explicit translation request

- User says: "Create a transcript PDF from this YouTube video and add a Chinese translation."
- Actions:
  1. Extract the source transcript first.
  2. Produce the polished source-language transcript.
  3. Add Chinese translation because it was explicitly requested.
- Result: Transcript package that clearly distinguishes source text from translated text.

## Output Location

Save the final PDF inside the current project folder unless the user asks for another path. Prefer a slugged filename derived from the video title.

Example:

```text
./cult-leaders-have-terrible-pitches.pdf
```

## Helper Scripts

Use `scripts/fetch_youtube_transcript.py` as the canonical extraction entrypoint. It must be the first script in the flow because it centralizes URL validation, metadata fetch, caption selection, quality checks, and optional ASR fallback.
Use `scripts/asr_faster_whisper.py` when captions are unavailable and audio can be downloaded. It writes segment JSON for the fallback path using a local faster-whisper model.

Use `scripts/assemble_transcript.py` to turn timed segments into readable transcript prose with coarse markers.
When chapter titles need to be inserted into the transcript body at precise positions, also write paragraph metadata JSON from the same script and pass it to the PDF renderer.
If reliable source chapters exist, also pass them into `assemble_transcript.py` so paragraph boundaries can align with chapter boundaries before PDF rendering.

Use `scripts/render_blog_pdf.py` to turn metadata, summary, chapters, and transcript text into a polished PDF without external PDF dependencies.
Use `scripts/validate_transcript_skill.py` during development to run offline regression checks for VTT parsing, overlap cleanup, marker insertion, chapter-aware transcript metadata, and PDF rendering.
Use `scripts/package_skill_release.py` before distribution to build a clean zip that excludes repo-only files such as `README.md`, `.git/`, `tests/`, and `__pycache__/`.

Typical flow:

```bash
python scripts/fetch_youtube_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID" --output-dir ./youtube_transcript_work
python scripts/asr_faster_whisper.py ./downloaded-audio.m4a --output ./youtube_transcript_work/segments.json --model small --device cpu --compute-type int8 --beam-size 1 --vad-filter
python scripts/assemble_transcript.py ./youtube_transcript_work/segments.json --output transcript.txt
python scripts/assemble_transcript.py ./youtube_transcript_work/segments.json --output transcript.txt --metadata-output transcript-metadata.json --chapter-breaks-json ./youtube_transcript_work/chapters.json
# Then read title/date/channel from ./youtube_transcript_work/metadata.json and pass them into the renderer.
python scripts/render_blog_pdf.py \
  --title "Cult Leaders Have Terrible Pitches" \
  --date "2025-09-16" \
  --channel "The Knowledge Project Podcast" \
  --summary-file summary.txt \
  --chapters-json ./youtube_transcript_work/chapters.json \
  --transcript-metadata-json transcript-metadata.json \
  --transcript transcript.txt \
  --output ./cult-leaders-have-terrible-pitches.pdf
python scripts/validate_transcript_skill.py
python scripts/package_skill_release.py
```

## Quality Checks

Before returning the result, verify:

- The transcript language matches the source content unless translation was explicitly requested
- The transcript is materially complete
- The chapter list is coherent
- Inline chapter headings appear at the right transcript positions when source chapters exist
- If adjacent chapter timestamps are less than one minute apart, collapse them to a single inline chapter heading
- Omit timestamps from inline chapter headings inside the transcript body
- The document has title, date, and source metadata
- The PDF was written successfully inside the project folder
- Body text is justified and aligned to the same width as the divider rules
- No page lets body text cross into the footer whitespace band
- The final document is readable as an article, not as raw subtitles

If extraction quality is poor, say so briefly and state whether the weakness comes from source captions or ASR.

## Troubleshooting

### No captions found

- Cause: The video has no manual or auto-generated captions.
- Action: Use ASR only if an ASR dependency is available. Otherwise stop and report the missing capability.

### Captions look incomplete

- Cause: Subtitle track omits spoken sections or is materially desynchronized.
- Action: Switch to ASR when available and say why the caption path was rejected.

### Wrong language track selected

- Cause: Multiple subtitle tracks exist and the wrong one was chosen automatically.
- Action: Prefer the original spoken language when known. If ambiguous, report the ambiguity and ask for a language only if it blocks reliable extraction.

### ASR fallback unavailable

- Cause: No local or hosted transcription path exists.
- Action: Report the missing dependency instead of pretending the transcript is complete.

### PDF renders but formatting is degraded

- Cause: Transcript blocks are too long, metadata is missing, or chapter placement is noisy.
- Action: Re-check transcript normalization, chapter inputs, and rendering inputs before returning the file.

### User wants only a summary

- Cause: The user asked for analysis but not a PDF deliverable.
- Action: Still extract or inspect the transcript as needed, but do not force PDF generation when the user explicitly wants summary-only output.

## Response Pattern

When handling a user request with this skill:

1. State whether the transcript came from native captions or ASR fallback.
2. Save the final PDF in the project folder.
3. Return the PDF path.
4. Return the summary.
5. Return the chapter breakdown.
6. Add translation only if explicitly requested.
