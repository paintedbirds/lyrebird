# Faster transcription: backend options for future versions

Status: **implemented 2026-07-23 — migrated to mlx-whisper `large-v3-turbo`.**
See `transcriber.py`. Original research below (2026-07-07) covered speed
only; the decision below also weighs accuracy, using a real benchmark tool
instead of vendor claims.

PyInstaller build verified 2026-07-23: `mlx.metallib` (compiled Metal
shaders), `libmlx.dylib`, and `mlx_whisper`'s tiktoken vocab assets all get
bundled automatically via `collect_all()` in `lyrebird.spec`, and the
packaged `.app` launches and stays up without crashing. Not yet done: the
same test on a genuinely clean machine (this run was on the dev box), and
re-running the benchmark with more clips.

## Decision: mlx-whisper large-v3-turbo

Built `lyrebird-benchmark/` (sibling folder, see its README) to compare
openai-whisper `small` (current), faster-whisper `small`, mlx-whisper
`large-v3-turbo`, and NVIDIA Parakeet TDT v3 (`parakeet-mlx`) on real audio
— WhatsApp voice notes, read Spanish text, and a long English paragraph.

Results across those 3 clips:

- **mlx-whisper large-v3-turbo**: 2-2.3x faster than current `whisper` where
  both completed, better WER (13.4% vs 19.6% on the Spanish clip; 9.0% vs
  no-result on the English one), never crashed, never switched language.
  One hallucination artifact (repeated foreign-language tokens) at the tail
  of the longest clip — known Whisper failure mode on long audio, not
  specific to this checkpoint.
- **parakeet-mlx**: fastest and best WER on clean read speech, but
  hallucinated entirely in English when given spontaneous Spanish speech
  (a WhatsApp voice note) — disqualifying until that's understood, and out
  of scope for now since it's an unofficial single-maintainer MLX port with
  no packaging precedent.
- **faster-whisper**: consistently the slowest of the four, no accuracy
  edge to compensate. Dropped from consideration.
- **whisper (current production)**: crashed on the one long English clip
  tested (`cannot reshape tensor of 0 elements into shape [1, 0, 12, -1]`,
  a PyTorch/openai-whisper internal error). Not investigated further —
  moot once this migration lands, but worth knowing this bug exists in
  what's shipping today.

Sample size is small (3 clips) but the direction was consistent across all
of them, and mlx was the only candidate with zero catastrophic failures.
Decision: migrate to mlx-whisper `large-v3-turbo`, dropping Intel Mac
support (mlx is Apple Silicon only — Lyrebird's user base is assumed to be
mostly Apple Silicon; revisit if that's wrong).

### Migration checklist

1. **Verify `mlx_whisper.transcribe()` accepts a numpy float32 array**, not
   just a file path — `transcriber.py`'s VAD auto-detect path
   (`_vad_segments()`) feeds per-phrase numpy chunks straight to the model,
   not file paths. If it only takes paths, each chunk needs a temp WAV
   round-trip first (see `lyrebird-benchmark/audio_utils.py` for that
   pattern already written).
2. **Rewrite `transcriber.py`**:
   - `DEFAULT_MODEL` → `"mlx-community/whisper-large-v3-turbo"` (still
     overridable via the `WHISPER_MODEL` env var).
   - `Transcriber.load()`: drop the `torch`/SIGABRT workaround
     (`set_num_threads(1)`, `set_grad_enabled(False)`) entirely — not
     applicable to MLX. Warm the model with a short throwaway transcribe
     call (mlx_whisper caches internally by `path_or_hf_repo`), same
     pattern as `lyrebird-benchmark/backends/mlx_backend.py`.
   - `Transcriber.transcribe()`: replace `self.model.transcribe(...)` calls
     with `mlx_whisper.transcribe(audio, path_or_hf_repo=self.model_name, ...)`.
     Drop the `fp16=False` arg (CPU-only concept, not applicable to MLX).
     Confirm `language=`, `initial_prompt=`, and `condition_on_previous_text=`
     kwargs exist on `mlx_whisper.transcribe` with the same meaning before
     assuming a 1:1 swap.
   - Leave `load_audio_file()` and `_vad_segments()` untouched — they're
     backend-agnostic.
3. **`requirements.txt`**: remove `openai-whisper` (drops the `torch`
   dependency transitively), add `mlx-whisper`.
4. **Packaging** (`lyrebird.spec`, `build_app.sh`, `build_dist.sh`): the
   biggest unverified risk. MLX ships compiled Metal shaders/dylibs that
   PyInstaller may not bundle automatically the way it does pure-Python
   packages. Needs a full build + run test on a clean machine before
   shipping, not just `python app.py` from source.
5. **Re-run the benchmark with more clips** before merging — 3 clips is not
   enough to trust blindly. Specifically want more spontaneous (not
   read-aloud) Spanish audio to see whether mlx also has a spontaneous-speech
   weak spot like parakeet did, since all 3 test clips happened to favor it.
6. **Manual QA in the actual app** once wired up: record → transcribe with
   both a forced language and auto-detect (the EN/ES-mixing VAD path),
   short clips and long ones.
7. Decide whether to keep an env-var escape hatch back to openai-whisper for
   users who hit an mlx/Metal issue post-launch, or cut it cleanly. Leaning
   cut-cleanly per no-speculative-fallback-code preference, but flag for
   confirmation before removing the option entirely.

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
