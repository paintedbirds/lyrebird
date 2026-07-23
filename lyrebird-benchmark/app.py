"""Lyrebird ASR benchmark CLI.

    python app.py record --out recordings/clip1.wav [--expected "expected text"]
    python app.py run recordings/clip1.wav [--mode isolated|parallel] [--repeats 3]
    python app.py dataset dataset/ [--mode isolated]

A .wav's expected transcript can be given inline with --expected or as a
same-named sidecar file (clip1.wav -> clip1.txt). Without one, WER is
skipped and only timing + raw transcripts are reported.
"""

from __future__ import annotations

import argparse
import os
import time

from backends import ALL_BACKENDS
from benchmark import run_isolated, run_parallel
from recorder import record_to_wav
from storage import save_results


def _sidecar_expected(audio_path: str) -> str | None:
    txt_path = os.path.splitext(audio_path)[0] + ".txt"
    if os.path.exists(txt_path):
        return open(txt_path, encoding="utf-8").read().strip()
    return None


def _build_backends(names):
    selected = names or list(ALL_BACKENDS.keys())
    return [ALL_BACKENDS[n]() for n in selected]


def _print_table(results):
    header = f"{'Backend':<28} {'Cold':>8} {'Warm avg':>10} {'Warm P95':>10} {'WER':>7}  Text / Error"
    print(header)
    print("-" * len(header))
    for r in results:
        if r.error:
            print(f"{r.backend_name:<28} {'FAILED':>8}  {r.error.splitlines()[-1][:80]}")
            continue
        cold = f"{r.cold_start_s:.2f}s" if r.cold_start_s is not None else "-"
        warm = f"{r.timing.mean:.2f}s" if r.timing.count else "-"
        p95 = f"{r.timing.p95:.2f}s" if r.timing.count else "-"
        wer = f"{r.wer * 100:.1f}%" if r.wer is not None else "-"
        preview = (r.text[:60] + "...") if len(r.text) > 60 else r.text
        print(f"{r.backend_name:<28} {cold:>8} {warm:>10} {p95:>10} {wer:>7}  {preview}")


def _results_to_rows(results, audio_path):
    rows = []
    for r in results:
        rows.append(
            {
                "audio": audio_path,
                "backend": r.backend_name,
                "cold_start_s": r.cold_start_s,
                "warm_mean_s": r.timing.mean if r.timing.count else None,
                "warm_p95_s": r.timing.p95 if r.timing.count else None,
                "wer": r.wer,
                "text": r.text,
                "error": r.error,
            }
        )
    return rows


def cmd_record(args):
    path = record_to_wav(args.out)
    print(f"Saved {path}")
    if args.expected:
        with open(os.path.splitext(path)[0] + ".txt", "w", encoding="utf-8") as f:
            f.write(args.expected)


def cmd_run(args):
    backends = _build_backends(args.backends)
    expected = args.expected or _sidecar_expected(args.audio)

    if args.mode == "parallel":
        results = run_parallel(backends, args.audio, expected_text=expected)
    else:
        results = run_isolated(backends, args.audio, repeats=args.repeats, expected_text=expected)

    _print_table(results)
    _write_results([r for r in _results_to_rows(results, args.audio)], args.mode)


AUDIO_EXTENSIONS = (".wav", ".opus", ".ogg", ".mp3", ".m4a", ".flac")


def cmd_dataset(args):
    backends = _build_backends(args.backends)
    audio_files = sorted(
        os.path.join(args.folder, f)
        for f in os.listdir(args.folder)
        if f.lower().endswith(AUDIO_EXTENSIONS)
    )
    if not audio_files:
        print(f"No audio files ({', '.join(AUDIO_EXTENSIONS)}) found in {args.folder}")
        return

    all_rows = []
    for audio_path in audio_files:
        expected = _sidecar_expected(audio_path)
        print(f"\n=== {audio_path} ===")
        results = run_isolated(backends, audio_path, repeats=args.repeats, expected_text=expected)
        _print_table(results)
        all_rows.extend(_results_to_rows(results, audio_path))

    print("\n=== Summary (mean across dataset) ===")
    by_backend = {}
    for row in all_rows:
        by_backend.setdefault(row["backend"], []).append(row)
    header = f"{'Backend':<28} {'Avg warm':>10} {'P95 warm':>10} {'Avg WER':>9} {'Fails':>6}"
    print(header)
    print("-" * len(header))
    for name, rows in by_backend.items():
        warm = [r["warm_mean_s"] for r in rows if r["warm_mean_s"] is not None]
        wers = [r["wer"] for r in rows if r["wer"] is not None]
        p95s = [r["warm_p95_s"] for r in rows if r["warm_p95_s"] is not None]
        fails = sum(1 for r in rows if r["error"])
        avg_warm = f"{sum(warm) / len(warm):.2f}s" if warm else "-"
        avg_p95 = f"{sum(p95s) / len(p95s):.2f}s" if p95s else "-"
        avg_wer = f"{sum(wers) / len(wers) * 100:.1f}%" if wers else "-"
        print(f"{name:<28} {avg_warm:>10} {avg_p95:>10} {avg_wer:>9} {fails:>6}")

    _write_results(all_rows, "dataset")


def _write_results(rows, tag):
    json_path, csv_path = save_results(rows, tag)
    print(f"\nSaved {json_path} and {csv_path}")


def main():
    parser = argparse.ArgumentParser(description="Lyrebird ASR backend benchmark")
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="Record one WAV clip via the microphone")
    p_record.add_argument("--out", default="recordings/clip.wav")
    p_record.add_argument("--expected", help="Ground-truth transcript, saved as a sidecar .txt")
    p_record.set_defaults(func=cmd_record)

    p_run = sub.add_parser("run", help="Benchmark all backends against one WAV file")
    p_run.add_argument("audio")
    p_run.add_argument("--mode", choices=["isolated", "parallel"], default="isolated")
    p_run.add_argument("--repeats", type=int, default=3, help="Transcribe calls per backend (1 cold + N-1 warm)")
    p_run.add_argument("--expected", help="Ground-truth transcript; overrides any sidecar .txt")
    p_run.add_argument("--backends", nargs="+", choices=list(ALL_BACKENDS.keys()))
    p_run.set_defaults(func=cmd_run)

    p_dataset = sub.add_parser("dataset", help="Run isolated benchmarks over every .wav in a folder")
    p_dataset.add_argument("folder")
    p_dataset.add_argument("--repeats", type=int, default=3)
    p_dataset.add_argument("--backends", nargs="+", choices=list(ALL_BACKENDS.keys()))
    p_dataset.set_defaults(func=cmd_dataset)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
