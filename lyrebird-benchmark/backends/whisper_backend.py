"""Current Lyrebird production backend: openai-whisper on PyTorch CPU.

Baseline for the benchmark — everything else is measured against this.
"""

from .base import Backend

MODEL_NAME = "small"


class WhisperBackend(Backend):
    name = "whisper_small"

    def __init__(self, model_name=MODEL_NAME):
        super().__init__()
        self.model_name = model_name
        self.model = None

    def load(self):
        import torch
        import whisper

        torch.set_num_threads(1)
        torch.set_grad_enabled(False)
        self.model = whisper.load_model(self.model_name)
        self.loaded = True

    def transcribe(self, audio_path: str) -> str:
        import torch

        with torch.no_grad():
            result = self.model.transcribe(audio_path, fp16=False, verbose=False)
        return result["text"].strip()
