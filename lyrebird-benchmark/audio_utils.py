"""Decode any input audio format to the 16kHz mono WAV every backend expects.

Reuses Lyrebird's own decoder (transcriber.load_audio_file) instead of
reimplementing it, so:
  - .opus (and .ogg/.mp3/.m4a/.flac) files decode exactly the same way here
    as they do in the production app — no separate opus-handling code path
    to keep in sync.
  - every backend in a benchmark run gets byte-identical audio, regardless
    of what format the input file was, which is the whole point of running
    "one audio through all models" fairly.
"""

import os
import sys
import tempfile

import numpy as np
from scipy.io import wavfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from transcriber import WHISPER_SR, load_audio_file  # noqa: E402


def normalize_to_wav(input_path: str) -> str:
    """Return a path to a 16kHz mono WAV version of input_path.

    Always writes a fresh temp file (even for .wav input) so every backend
    sees audio decoded through the exact same path, rather than trusting
    that an uploaded .wav is already 16kHz mono PCM.
    """
    audio = load_audio_file(input_path)
    fd, wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    pcm16 = np.int16(np.clip(audio, -1.0, 1.0) * 32767)
    wavfile.write(wav_path, WHISPER_SR, pcm16)
    return wav_path
