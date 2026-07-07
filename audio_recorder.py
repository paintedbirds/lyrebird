"""Microphone recording using sounddevice, saved with scipy.

Records mono audio at 16kHz (Whisper's native sample rate) so the recorded
audio can be fed straight into the model without resampling.
"""

import os
import tempfile

import numpy as np
import sounddevice as sd
from scipy.io import wavfile


SAMPLE_RATE = 16000  # Whisper expects 16kHz


def list_input_devices():
    """Return [(index, name)] for devices that can capture audio."""
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((i, d["name"]))
    except Exception:
        pass
    return out


def resolve_device(name):
    """Map a saved device name to a current index, or None for system default."""
    if not name:
        return None
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0 and d["name"] == name:
                return i
    except Exception:
        pass
    return None


class Recorder:
    def __init__(self, samplerate=SAMPLE_RATE):
        self.samplerate = samplerate
        self._frames = []
        self._stream = None
        self.recording = False
        self.level = 0.0  # smoothed mic level (0..1) for the waveform UI
        self.device_name = None  # None = system default microphone

    def set_device(self, name):
        self.device_name = name or None

    def _callback(self, indata, frames, time_info, status):
        # status holds xrun/overflow flags; ignore for a simple recorder.
        self._frames.append(indata.copy())
        if indata.size:
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            lvl = min(1.0, rms * 12.0)
            # Fast attack, slow release: bars jump with speech, settle in pauses
            if lvl > self.level:
                self.level = 0.4 * self.level + 0.6 * lvl
            else:
                self.level = 0.88 * self.level + 0.12 * lvl

    def start(self):
        """Open the input stream and begin capturing frames."""
        self._frames = []
        self.level = 0.0
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="float32",
            callback=self._callback,
            device=resolve_device(self.device_name),
        )
        self._stream.start()
        self.recording = True

    def stop(self):
        """Stop recording.

        Returns (audio, wav_path):
          audio    - float32 numpy array (16kHz mono) ready for Whisper, or None
          wav_path - path to a saved WAV copy of the recording, or None
        """
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.recording = False

        if not self._frames:
            return None, None

        audio = np.concatenate(self._frames, axis=0).flatten().astype(np.float32)

        # Save a WAV copy with scipy (int16 PCM, widely compatible).
        wav_path = os.path.join(tempfile.gettempdir(), "whisper_menubar_recording.wav")
        pcm16 = np.int16(np.clip(audio, -1.0, 1.0) * 32767)
        wavfile.write(wav_path, self.samplerate, pcm16)

        return audio, wav_path
