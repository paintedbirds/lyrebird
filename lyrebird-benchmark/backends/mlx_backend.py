"""mlx-whisper large-v3-turbo — Option B from docs/transcription-backends.md.

Runs on the Apple Silicon GPU via MLX/Metal. mlx_whisper caches the loaded
model internally keyed by `path_or_hf_repo`, so calling transcribe() again
with the same repo id reuses the already-loaded model instead of reloading.
"""

from .base import Backend

MODEL_REPO = "mlx-community/whisper-large-v3-turbo"


class MlxWhisperBackend(Backend):
    name = "mlx_whisper_large_v3_turbo"

    def __init__(self, model_repo=MODEL_REPO):
        super().__init__()
        self.model_repo = model_repo
        self._mlx_whisper = None

    def load(self):
        import os
        import tempfile

        import mlx_whisper
        import numpy as np
        from scipy.io import wavfile

        self._mlx_whisper = mlx_whisper

        # mlx_whisper has no standalone load() call; it downloads and
        # populates its internal model cache (keyed by path_or_hf_repo) on
        # the first transcribe(). Do that here with a throwaway silent clip
        # so the download + first-load cost isn't counted as "cold start".
        silence = np.zeros(16000, dtype=np.float32)  # 1s @ 16kHz
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            wavfile.write(wav_path, 16000, silence)
            mlx_whisper.transcribe(wav_path, path_or_hf_repo=self.model_repo)
        finally:
            os.unlink(wav_path)

        self.loaded = True

    def transcribe(self, audio_path: str) -> str:
        result = self._mlx_whisper.transcribe(
            audio_path, path_or_hf_repo=self.model_repo
        )
        return result["text"].strip()
