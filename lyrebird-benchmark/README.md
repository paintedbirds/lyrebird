# Lyrebird ASR benchmark

Standalone tool to decide Lyrebird's transcription backend with real
numbers instead of vendor claims. One recording, sent to every engine, so
the comparison is fair (same audio) — see `docs/transcription-backends.md`
in the main repo for the research that led here.

## Setup

Separate venv from the main app — this pulls in torch, mlx, and an
unofficial community package the main app doesn't (and might never) ship.

```bash
cd lyrebird-benchmark
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`parakeet-mlx` and `mlx-whisper` require ffmpeg on PATH (`brew install ffmpeg`)
and only run on Apple Silicon.

## Usage

Record a clip and save the ground-truth transcript alongside it:

```bash
python app.py record --out recordings/clip1.wav --expected "We need to update the financial design before tomorrow"
```

Benchmark every backend against it (isolated mode — the number that should
actually decide the backend, since nothing else is competing for CPU/GPU):

```bash
python app.py run recordings/clip1.wav
```

Quick side-by-side look under contention (not for the final decision):

```bash
python app.py run recordings/clip1.wav --mode parallel
```

Run a full dataset (e.g. `dataset/spanish-01.wav` + `dataset/spanish-01.txt`
sidecar transcripts) and get averaged stats with P95:

```bash
python app.py dataset dataset/
```

Every run also writes JSON + CSV to `results/` for later analysis.

## Backends

| id | engine | notes |
|---|---|---|
| `whisper` | openai-whisper `small` | current Lyrebird production backend |
| `faster_whisper` | faster-whisper `small`, int8 CPU | Option A, portable |
| `mlx` | mlx-whisper `large-v3-turbo` | Option B, Apple Silicon GPU |
| `parakeet` | parakeet-mlx `parakeet-tdt-0.6b-v3` | unofficial port, maturity unproven |

Restrict a run to specific backends with `--backends whisper mlx`.
