"""Microphone recording for the benchmark: press Enter to start, Enter to stop.

Same sample rate and WAV format as Lyrebird's own audio_recorder.py, so a
benchmark recording is representative of what the real app would capture.
"""

import os

import numpy as np
import sounddevice as sd
from scipy.io import wavfile

SAMPLE_RATE = 16000


def record_to_wav(out_path: str) -> str:
    """Block until Enter is pressed twice, then write a mono 16kHz WAV."""
    frames = []

    def callback(indata, _frame_count, _time_info, _status):
        frames.append(indata.copy())

    input("Press Enter to start recording...")
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback
    )
    stream.start()
    input("Recording... press Enter to stop.")
    stream.stop()
    stream.close()

    if not frames:
        raise RuntimeError("No audio captured.")

    audio = np.concatenate(frames, axis=0).flatten().astype(np.float32)
    pcm16 = np.int16(np.clip(audio, -1.0, 1.0) * 32767)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    wavfile.write(out_path, SAMPLE_RATE, pcm16)
    return out_path
