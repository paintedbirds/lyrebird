"""Local Whisper transcription wrapper.

Loads an OpenAI Whisper model once and reuses it for every transcription.
Everything runs on-device; no network calls are made after the model file
has been downloaded on first use.
"""

import os
import threading


# Map of the human-friendly labels shown in the UI to Whisper language codes.
# None means "let Whisper auto-detect the language".
LANGUAGES = [
    ("Auto-detect", None),
    ("Spanish", "es"),
    ("English", "en"),
    ("Portuguese", "pt"),
    ("French", "fr"),
    ("German", "de"),
    ("Italian", "it"),
]

# Default model. "small" is a good speed/accuracy balance for ES/EN on CPU.
# Override with the WHISPER_MODEL env var (e.g. tiny, base, small, medium).
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "small")


class Transcriber:
    def __init__(self, model_name=DEFAULT_MODEL):
        self.model_name = model_name
        self.model = None
        self._lock = threading.Lock()
        self._vad = None

    def load(self):
        """Load the model into memory. First run downloads it (~460MB for small)."""
        import torch
        import whisper  # imported lazily so the menu bar shows up fast

        with self._lock:
            if self.model is None:
                # Stability on macOS: single-threaded, inference-only. Avoids the
                # PyTorch SIGABRT seen with multithreaded grad-mode toggling.
                try:
                    torch.set_num_threads(1)
                    torch.set_grad_enabled(False)
                except Exception:
                    pass
                self.model = whisper.load_model(self.model_name)
        return self.model

    def transcribe(self, audio, language=None, initial_prompt=None):
        """Transcribe an audio file path or a float32 numpy array (16kHz mono).

        Returns the transcribed text. `language` is a Whisper code like "es"
        or None for auto-detect. `initial_prompt` is an optional string of
        custom vocabulary (names, jargon) that biases Whisper's decoding
        toward those words/spellings without any fine-tuning.

        On auto-detect, the audio is split on pauses and each phrase is detected
        and transcribed independently, so a recording that mixes English and
        Spanish keeps each part in the language it was actually spoken. Forcing a
        specific language skips this and does a single pass in that language.
        """
        import torch

        if self.model is None:
            self.load()

        prompt = initial_prompt.strip() if initial_prompt else None

        with torch.no_grad():
            if language is None:
                segments = self._vad_segments(audio)
                if segments and len(segments) > 1:
                    parts = []
                    for chunk in segments:
                        res = self.model.transcribe(
                            chunk,
                            language=None,
                            fp16=False,
                            verbose=False,
                            condition_on_previous_text=False,
                            initial_prompt=prompt,
                        )
                        txt = res["text"].strip()
                        if txt:
                            parts.append(txt)
                    return " ".join(parts).strip()

            result = self.model.transcribe(
                audio,
                language=language,
                fp16=False,      # CPU has no fp16; avoids a noisy warning
                verbose=False,
                initial_prompt=prompt,
            )
        return result["text"].strip()

    def _vad_segments(self, audio):
        """Split audio into per-phrase chunks on silence using Silero VAD.

        Returns a list of float32 numpy chunks (16kHz), or None if VAD is
        unavailable or the audio is too short / has no clear pauses.
        """
        try:
            import whisper
            from silero_vad import get_speech_timestamps, load_silero_vad
        except Exception:
            return None

        arr = whisper.load_audio(audio) if isinstance(audio, str) else audio
        if arr is None or len(arr) < 16000:  # under ~1s: not worth splitting
            return None

        if self._vad is None:
            self._vad = load_silero_vad()

        timestamps = get_speech_timestamps(
            arr,
            self._vad,
            sampling_rate=16000,
            min_silence_duration_ms=300,
            # Padding around each detected speech span. Bumped up from 200ms:
            # at 200 the first/last word of a phrase was sometimes clipped by
            # the VAD boundary before Whisper ever saw it.
            speech_pad_ms=350,
        )
        if not timestamps:
            return None
        return [arr[t["start"]:t["end"]] for t in timestamps]
