# Faster transcription: backend options for future versions

Status: researched 2026-07-07, not implemented. Current backend stays as-is
(openai-whisper on PyTorch CPU) until one of these lands.

## Why the current setup is slow

`transcriber.py` runs OpenAI's reference `whisper` package on PyTorch CPU.
To avoid a macOS SIGABRT (duplicate OpenMP runtimes + multithreaded
grad-mode toggling) it also pins `torch.set_num_threads(1)`, so inference
uses a single core. That is the main bottleneck; the model itself is fine.

## Option A: faster-whisper (CTranslate2)

- Same Whisper checkpoints, different inference engine. ~4x faster on CPU
  with `compute_type="int8"`; WER degradation from int8 is negligible
  (tenths of a percent in the project's published benchmarks).
- Removes the PyTorch dependency entirely, which also removes the SIGABRT
  workaround and the single-thread pin.
- Runs everywhere: Apple Silicon, Intel Macs, Linux. Safest choice for
  distributed builds.
- Ships built-in VAD, so the Silero VAD code in `transcriber.py` could be
  simplified or dropped.
- Mature, de facto standard for local Whisper. Well-documented PyInstaller
  packaging stories.
- Speed headroom can be spent on accuracy: `medium` on int8 runs roughly at
  the speed `small` runs today, and `medium` is noticeably better for
  Spanish with jargon/proper nouns.
- Agent skill with migration guidance (1.4K installs):
  `npx skills add theplasmak/faster-whisper@faster-whisper -g`
  https://skills.sh/theplasmak/faster-whisper/faster-whisper

## Option B: mlx-whisper (Apple MLX)

- Runs on the Apple Silicon GPU. On an M4 Pro it is likely the fastest
  option, especially for large models (`medium`, `large-v3`) and long audio.
- Apple Silicon only: an Intel Mac build cannot use it.
- Models are MLX-format conversions downloaded from Hugging Face (not the
  original checkpoints, though weights are equivalent).
- Younger ecosystem; less documented PyInstaller packaging.

## For Lyrebird's use case

Short dictation clips (seconds): both options move transcription from
"several seconds" to sub-second with `small`. MLX's advantage shows up with
long audio or large models.

## Recommended path

1. First migration: faster-whisper with `compute_type="int8"` (portability,
   maturity, drops torch). Consider bumping the default model to `medium`.
2. Later, optional: a selectable backend layer — mlx-whisper when running on
   Apple Silicon and the package is available, faster-whisper as fallback.
   Adds maintenance cost; only worth it if large-model interactive speed on
   Apple Silicon becomes a goal.
3. Perceived-speed win independent of engine: start transcribing chunks
   while still recording (streaming with the existing Silero VAD), so most
   of the work is done by the time recording stops.
