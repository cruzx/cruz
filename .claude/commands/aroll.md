---
description: "Auto rough-cut A-roll: Whisper transcribe → analyze edit points → generate Final Cut Pro FCPXML rough cut"
---

# A-Roll Auto Rough Cut For Final Cut Pro

Automate the tedious rough cut of talking-head / voiceover footage. Give it a folder of clips, and it will transcribe, detect keep/drop segments, and build a Final Cut Pro importable rough cut as an `FCPXML` file.

## Input

$ARGUMENTS

If the user did not provide enough info, ask for:
1. **Footage folder path** (required)
2. **Landscape or portrait** (required) — landscape: 3840x2160 | portrait: 2160x3840, or let the user specify custom resolution
3. **Project name** (optional) — inferred from folder name if not provided
4. **Frame rate** (optional) — default 23.976. Common options: 23.976 / 24 / 25 / 29.97 / 30 / 50 / 59.94 / 60
5. **Language** (optional) — default auto-detect. Examples: Chinese, English, Japanese, etc.

## Workflow

### Step 1: Scan footage
- Scan the folder for video files (.MP4, .mp4, .MOV, .mov, .mxf, .MXF, .avi, .AVI)
- Sort by filename (usually contains shooting sequence number)
- List found files and confirm with the user before proceeding

### Step 2: Extract audio
- Use FFmpeg to extract 16kHz mono WAV from each video
- Command: `ffmpeg -i input.mp4 -vn -ar 16000 -ac 1 output.wav`

### Step 3: Transcribe with Whisper
- Transcribe each audio file using OpenAI Whisper with word-level timestamps
- Command: `whisper audio.wav --model medium --language {LANGUAGE} --word_timestamps True --output_format json`
- If language is set to auto-detect, omit the `--language` flag

### Step 4: Silence detection
- Use FFmpeg silencedetect to find silent gaps
- Command: `ffmpeg -i audio.wav -af silencedetect=noise={SILENCE_THRESHOLD}:d={MIN_SILENCE_DURATION} -f null -`
- Default threshold: -50dB, default minimum silence duration: 0.8s

### Step 5: Analyze edit points
Combine transcription and silence data to decide what to keep and what to cut:

**Keep/drop markers** — The creator may use spoken markers during recording to flag segments. Default markers:
- **Keep markers**: "OK", "好", "这条好", "keep", "good", "nice" (the segment *before* this marker is kept)
- **Drop markers**: "pass", "不要", "重来", "cut", "again", "redo" (the segment before this marker is dropped)

If no markers are detected in the entire session, treat all non-silent speech segments as kept (the creator didn't use a marker workflow).

**Cutting rules:**
- Remove silent gaps between speech segments
- Remove repeated takes of the same content — when multiple takes exist, keep the last good take (the one closest to a keep marker, or the last one if no markers)
- Trim leading/trailing dead air from each clip
- Collect all kept segments as `(source_filename, in_point_seconds, out_point_seconds)`

**After analysis, present the edit decision list to the user for review before proceeding.** Show: segment number, source file, in/out timecodes, first few words of transcript, and reason (kept/cut). Wait for user confirmation.

### Step 6: Generate Final Cut Pro FCPXML
Generate an `FCPXML` document (saved inside the footage folder) that Final Cut Pro can import as a rough-cut timeline.

Requirements for the generated `FCPXML`:
1. Use one project/timeline named after the provided project name.
2. Register each source clip as an asset with an absolute file URL.
3. Set the timeline format from the requested resolution and frame rate.
4. Place all kept segments on the primary storyline in shooting order.
5. Preserve each kept segment's source in/out points accurately enough for rough-cut review.
6. Save the file as `{project_name}.fcpxml` inside the footage folder.

When generating the XML:
- Prefer an `FCPXML` version that modern Final Cut Pro imports cleanly, such as `1.10`, unless the user requests another version.
- Build stable IDs for formats, assets, and clips so the document is easy to inspect and re-generate.
- Use absolute POSIX file paths and convert them to `file://` URLs.
- If clip duration metadata is missing, probe it with `ffprobe` before writing the XML.

### Step 7: Generate companion review files
- Generate a merged SRT file based on the **timeline time** (record time), not source file time
- Timecodes must align to the edited rough cut
- Save the `.srt` file in the footage folder as a sidecar review artifact
- Also save a human-readable edit decision report (Markdown or TXT) listing segment number, source file, in/out timecodes, transcript preview, and keep/cut reason

### Step 8: Deliver into Final Cut Pro
- Confirm Final Cut Pro is installed before trying to hand off the timeline:
  - macOS: `mdfind \"kMDItemCFBundleIdentifier == 'com.apple.FinalCut'\" | head -n 1`
- If Final Cut Pro is available, reveal the generated `.fcpxml` path and offer to open it with Final Cut Pro:
  - macOS: `open -a \"Final Cut Pro\" \"{project_name}.fcpxml\"`
- If automatic opening is not reliable, tell the user the exact `.fcpxml` path and the import path inside Final Cut Pro:
  - `File -> Import -> XML...`
- Report the generated files at the end:
  - `{project_name}.fcpxml`
  - `{project_name}.srt`
  - edit decision report

## Configuration Reference

These defaults can be adjusted per-run by telling the assistant your preferences:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Resolution | 3840x2160 (landscape) | Output timeline resolution |
| Frame rate | 23.976 fps | Timeline frame rate |
| Language | auto-detect | Whisper transcription language |
| Whisper model | medium | Model size: tiny / base / small / medium / large |
| Silence threshold | -50 dB | Below this level counts as silence |
| Min silence duration | 0.8s | Minimum gap length to cut |
| Keep markers | OK, 好, keep, good | Spoken words that mark a good take |
| Drop markers | pass, 不要, cut, again | Spoken words that mark a bad take |
| FCPXML version | 1.10 | Final Cut Pro XML interchange version |

## Key Rules
- One folder = one project = one Final Cut Pro rough-cut timeline + one SRT
- All source clips are laid out on a single timeline in shooting order
- Intermediate files (WAV, JSON) are kept until the user says to clean up
- Always show the edit decision list before executing — never auto-cut without confirmation
- If Final Cut Pro import fails, keep the generated `FCPXML` and report the exact import error instead of silently changing formats
