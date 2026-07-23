"""faster-whisper (CTranslate2) — Option A from docs/transcription-backends.md.

Same Whisper checkpoints as whisper_backend.py, different inference engine.
int8 on CPU, portable across Intel and Apple Silicon Macs.
"""

from .base import Backend

MODEL_NAME = "small"


class FasterWhisperBackend(Backend):
    name = "faster_whisper_small"

    def __init__(self, model_name=MODEL_NAME, compute_type="int8"):
        super().__init__()
        self.model_name = model_name
        self.compute_type = compute_type
        self.model = None

    def load(self):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            self.model_name, device="cpu", compute_type=self.compute_type
        )
        self.loaded = True

    def transcribe(self, audio_path: str) -> str:
        segments, _info = self.model.transcribe(audio_path)
        return " ".join(seg.text.strip() for seg in segments).strip()
