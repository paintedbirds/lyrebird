"""Backend registry.

Each module here wraps one ASR engine behind the Backend interface from
base.py. Import lazily inside each backend's load() so that missing an
optional dependency (e.g. parakeet-mlx not installed) only breaks that one
backend instead of the whole benchmark.
"""

from .whisper_backend import WhisperBackend
from .faster_whisper_backend import FasterWhisperBackend
from .mlx_backend import MlxWhisperBackend
from .parakeet_backend import ParakeetBackend

ALL_BACKENDS = {
    "whisper": WhisperBackend,
    "faster_whisper": FasterWhisperBackend,
    "mlx": MlxWhisperBackend,
    "parakeet": ParakeetBackend,
}
