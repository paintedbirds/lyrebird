"""Common interface every backend under test implements.

Keeping load() and transcribe() separate is what lets the benchmark
distinguish cold start (first transcribe after load) from warm start
(subsequent transcribes with the model already resident in memory).
"""

from abc import ABC, abstractmethod


class Backend(ABC):
    #: Short id used in result tables and output filenames.
    name = "backend"

    def __init__(self):
        self.loaded = False

    @abstractmethod
    def load(self):
        """Load the model into memory. Called once before any transcribe()."""
        raise NotImplementedError

    @abstractmethod
    def transcribe(self, audio_path: str) -> str:
        """Transcribe a WAV file path and return the text."""
        raise NotImplementedError
