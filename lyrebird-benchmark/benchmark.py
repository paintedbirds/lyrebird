"""Runs the same audio through every backend and collects timing + WER.

Two modes, per the plan this scaffold implements:

- isolated: one backend at a time, nothing else competing for CPU/GPU/RAM.
  This is the number that should decide Lyrebird's backend.
- parallel: all backends transcribing the same clip at once, via threads.
  Useful for a quick side-by-side look, not for the final decision — under
  real contention every backend's numbers get worse than in isolation.
"""

import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from audio_utils import normalize_to_wav
from metrics import TimingStats, compute_wer


@dataclass
class BackendRunResult:
    backend_name: str
    text: str = ""
    cold_start_s: Optional[float] = None
    timing: TimingStats = field(default_factory=TimingStats)
    wer: Optional[float] = None
    wer_detail: Optional[str] = None
    error: Optional[str] = None


def _run_one_backend(backend, audio_path: str, repeats: int, expected_text: Optional[str]):
    result = BackendRunResult(backend_name=backend.name)
    try:
        backend.load()

        t0 = time.perf_counter()
        text = backend.transcribe(audio_path)
        result.cold_start_s = time.perf_counter() - t0
        result.text = text

        for _ in range(max(0, repeats - 1)):
            t0 = time.perf_counter()
            text = backend.transcribe(audio_path)
            result.timing.samples.append(time.perf_counter() - t0)
            result.text = text  # keep the last transcript for display

        if expected_text:
            wer_result = compute_wer(expected_text, result.text)
            result.wer = wer_result.wer
            result.wer_detail = (
                f"sub={wer_result.substitutions} del={wer_result.deletions} "
                f"ins={wer_result.insertions}"
            )
    except Exception:  # noqa: BLE001 — a broken/uninstalled backend shouldn't kill the run
        result.error = traceback.format_exc(limit=3)
    return result


def run_isolated(backends, audio_path: str, repeats=3, expected_text=None):
    """One backend fully loaded, benchmarked, and torn down before the next."""
    wav_path = normalize_to_wav(audio_path)
    try:
        results = []
        for backend in backends:
            results.append(_run_one_backend(backend, wav_path, repeats, expected_text))
        return results
    finally:
        os.unlink(wav_path)


def run_parallel(backends, audio_path: str, expected_text=None):
    """All backends loaded up front, then transcribing the same clip at once."""
    wav_path = normalize_to_wav(audio_path)
    results = {b.name: BackendRunResult(backend_name=b.name) for b in backends}
    ready = []
    for backend in backends:
        try:
            backend.load()
            ready.append(backend)
        except Exception:  # noqa: BLE001 — e.g. an optional backend isn't installed
            results[backend.name].error = traceback.format_exc(limit=3)

    def _transcribe(backend):
        t0 = time.perf_counter()
        text = backend.transcribe(wav_path)
        elapsed = time.perf_counter() - t0
        return backend.name, text, elapsed

    try:
        with ThreadPoolExecutor(max_workers=max(1, len(ready))) as pool:
            futures = [pool.submit(_transcribe, b) for b in ready]
            for future in futures:
                try:
                    name, text, elapsed = future.result()
                    results[name].text = text
                    results[name].cold_start_s = elapsed
                    if expected_text:
                        wer_result = compute_wer(expected_text, text)
                        results[name].wer = wer_result.wer
                except Exception:  # noqa: BLE001
                    pass  # the failing backend's future carries no name; skip it
    finally:
        os.unlink(wav_path)

    return list(results.values())
