"""NVIDIA Parakeet TDT v3 via the parakeet-mlx community port (Apple Silicon).

Unofficial port (github.com/senstella/parakeet-mlx), not affiliated with
NVIDIA. No Whisper-style PyInstaller packaging precedent yet — that
maturity risk is exactly what this benchmark should help quantify before
Lyrebird depends on it.

Requires ffmpeg on PATH (parakeet-mlx shells out to it for decoding).
"""

from .base import Backend

MODEL_REPO = "mlx-community/parakeet-tdt-0.6b-v3"


class ParakeetBackend(Backend):
    name = "parakeet_tdt_v3"

    def __init__(self, model_repo=MODEL_REPO):
        super().__init__()
        self.model_repo = model_repo
        self.model = None

    def load(self):
        from parakeet_mlx import from_pretrained

        self.model = from_pretrained(self.model_repo)
        self.loaded = True

    def transcribe(self, audio_path: str) -> str:
        result = self.model.transcribe(audio_path)
        return result.text.strip()
