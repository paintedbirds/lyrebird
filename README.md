# Whisper Menu Bar

A 100% local speech-to-text app for macOS. Lives in the menu bar (no Dock
icon) and transcribes audio with OpenAI Whisper running entirely on your
machine. No internet, no API keys.

## Features

- Menu bar only app (top right), launched with `python app.py`
- **Tap the menu bar icon to start listening immediately** — a floating "pill"
  appears, pinned on top of every app, with an animated waveform
- Keep using your Mac while it records; the pill stays put until you finish it
- **✓ finishes** (transcribe + auto-copy to clipboard); **✕ cancels**
- Result is copied to the clipboard automatically
- **Mixed English/Spanish**: on auto-detect, the audio is split on pauses and
  each phrase is detected separately, so English stays English and Spanish stays
  Spanish (see "Bilingual speech" below)
- Right-click the icon for a menu: Language, History, Settings…, Transcribe
  file…, Quit
- **Settings window**: pick the Whisper model, language, microphone, and toggle
  auto-copy. Choices are saved and restored on the next launch.
- **History**: the last 5 transcriptions are kept; click one to re-copy it to
  the clipboard
- **Transcribe a file** (right-click → Transcribe file…): Opus/WhatsApp voice
  notes, MP3, WAV, M4A, MP4, OGG, FLAC, AMR, 3GP, and more
- Uses the Whisper `small` model by default (changeable in Settings)

## Requirements

- macOS
- Python 3.9+
- **ffmpeg** (needed to decode uploaded MP3/M4A/MP4 files)

## Setup

```bash
cd ~/whisper-menubar

# 1. ffmpeg (for file uploads)
brew install ffmpeg

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies (this installs PyTorch too; may take a few minutes)
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
python app.py
```

A mic icon appears in the menu bar.

- **Left-click** the icon → the pill appears and recording starts right away.
  Speak, navigate around your Mac freely, then click **✓** to finish (the text
  lands on your clipboard) or **✕** to cancel. Left-clicking the icon again also
  finishes.
- **Right-click** the icon → menu with Language, Transcribe file…, and Quit.

The first run downloads the `small` model (~460 MB) into `~/.cache/whisper`,
plus a tiny Silero VAD model. After that everything is offline.

## Bilingual speech (English + Spanish)

Whisper commits to a single language per recording, so a mixed clip normally
collapses into one language (and may even translate the other parts). To handle
code-switching, this app — when **Language is set to Auto-detect** — splits the
audio on natural pauses and detects + transcribes each phrase on its own. A
sentence in English comes out in English; the next one in Spanish comes out in
Spanish.

Caveat: this works at pause boundaries. A switch in the *middle* of a sentence
with no pause (e.g. "voy a comprar milk") still gets transcribed as that
phrase's dominant language. Keep Language on **Auto-detect** for mixed speech;
forcing a specific language disables the per-phrase splitting.

### Shell alias (optional)

Add to `~/.zshrc` so you can launch it with one word:

```bash
alias whisper-app="source ~/whisper-menubar/.venv/bin/activate && python ~/whisper-menubar/app.py"
```

Then run `whisper-app` from any terminal.

## Permissions

The first time you record, macOS asks for **microphone** access for the app
that launched Python (usually Terminal or iTerm). Approve it, then record
again. You can manage this later in System Settings → Privacy & Security →
Microphone.

## Settings and history

Right-click the menu bar icon → **Settings…** to configure:

- **Model**: `tiny`, `base`, `small` (default), `medium`, `large-v3`. Changing it
  reloads in the background; a model you haven't used yet downloads on first
  selection. Bigger = more accurate but slower on CPU.
- **Language**: Auto-detect (best for mixed English/Spanish) or a fixed language.
- **Microphone**: choose the input device, or leave on System default.
- **Copy to clipboard automatically**: on by default.

All settings and the last 5 transcriptions persist in
`~/Library/Application Support/WhisperMenuBar/config.json`. Right-click →
**History (last 5)** to re-copy a recent transcription; **Clear history** wipes
it.

You can still set the starting model with the `WHISPER_MODEL` environment
variable (used until you change it in Settings):

```bash
WHISPER_MODEL=medium python app.py
```

## How it works

- `app.py` is a native AppKit/PyObjC app (no rumps, no Tkinter). It creates the
  menu bar `NSStatusItem` and a borderless floating `NSPanel` (the pill) in one
  Cocoa run loop. The pill is a non-activating panel pinned at `NSStatusWindow`
  level across all Spaces, so it floats over other apps and never steals focus —
  you keep typing in whatever app you were in. The waveform is a custom `NSView`
  driven by the live mic level. The Whisper model loads once on a background
  thread; UI updates are marshaled back with `AppHelper.callAfter`.
- `transcriber.py` wraps Whisper model loading and transcription, including the
  Silero-VAD per-phrase splitting used for bilingual auto-detect.
- `audio_recorder.py` records mic input at 16 kHz mono with sounddevice (and
  exposes a smoothed level for the waveform), saving a WAV copy with scipy.

Recording is transcribed directly from memory (no ffmpeg needed). Files are
decoded by Whisper using ffmpeg, which is why ffmpeg is required for the
Transcribe file… feature.

## Troubleshooting

- **No mic icon appears**: run from a terminal and watch for errors. Make sure
  the virtualenv is active.
- **File transcription fails / "ffmpeg not found"**: `brew install ffmpeg`.
- **Microphone records silence**: grant mic permission to your terminal app
  (see Permissions) and check the input device in System Settings → Sound.
- **Mixed languages still collapse**: make sure Language is on **Auto-detect**
  (right-click the icon → Language). Forcing a language disables per-phrase
  splitting.
