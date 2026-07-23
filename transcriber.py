"""Local mlx-whisper transcription wrapper.

Loads an mlx-whisper model once and reuses it for every transcription.
Everything runs on-device, on the Apple Silicon GPU via MLX/Metal; no
network calls are made after the model has been downloaded on first use.
"""

import os
import shutil
import subprocess
import tempfile
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

# Default model: an MLX-converted checkpoint from mlx-community on Hugging
# Face. Override with the WHISPER_MODEL env var (any mlx-community whisper
# repo id).
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")

WHISPER_SR = 16000


def load_audio_file(path):
    """Decode an audio file to float32 mono 16kHz without needing ffmpeg.

    mlx_whisper accepts a numpy array directly, but its own path-based
    decoding shells out to the ffmpeg CLI, which is not on PATH when the
    bundled app is launched from Finder/Spotlight. Instead:

    1. soundfile (bundled libsndfile): opus, ogg, flac, mp3, wav.
    2. afconvert (ships with macOS): m4a, aac, mp4, mov, caf.
    3. ffmpeg CLI, if present, as a last resort for anything else.
    """
    err = None
    try:
        return _load_with_soundfile(path)
    except Exception as exc:  # noqa: BLE001
        err = exc

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            subprocess.run(
                ["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@16000",
                 "-c", "1", path, wav_path],
                capture_output=True, check=True,
            )
            return _load_with_soundfile(wav_path)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass

    if _find_ffmpeg():
        import mlx_whisper.audio as mlx_audio

        return mlx_audio.load_audio(path)

    raise RuntimeError("Could not decode %s: %s" % (os.path.basename(path), err))


def _load_with_soundfile(path):
    import numpy as np
    import soundfile as sf

    data, sr = sf.read(path, dtype="float32", always_2d=True)
    data = data.mean(axis=1)  # downmix to mono
    if sr != WHISPER_SR:
        from scipy.signal import resample_poly
        from math import gcd

        g = gcd(WHISPER_SR, sr)
        data = resample_poly(data, WHISPER_SR // g, sr // g).astype(np.float32)
    return data


def _find_ffmpeg():
    """Locate ffmpeg even under Finder's minimal PATH and expose it."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for cand in ("/opt/homebrew/bin", "/usr/local/bin"):
        if os.path.exists(os.path.join(cand, "ffmpeg")):
            os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + cand
            return os.path.join(cand, "ffmpeg")
    return None


class Transcriber:
    def __init__(self, model_name=DEFAULT_MODEL):
        self.model_name = model_name
        self.model = None
        self._lock = threading.Lock()
        self._vad = None

    def load(self):
        """Warm the mlx-whisper model. First run downloads it from HF Hub."""
        import numpy as np
        import mlx_whisper

        with self._lock:
            if self.model is None:
                # mlx_whisper has no standalone load(); it populates its
                # internal model cache (keyed by path_or_hf_repo) on the
                # first transcribe() call. Warm it here with a throwaway
                # silent clip so first-dictation latency doesn't pay for it.
                silence = np.zeros(WHISPER_SR, dtype=np.float32)  # 1s
                mlx_whisper.transcribe(silence, path_or_hf_repo=self.model_name)
                self.model = self.model_name
        return self.model

    def transcribe(self, audio, language=None, initial_prompt=None):
        """Transcribe an audio file path or a float32 numpy array (16kHz mono).

        Returns (text, detected_lang). `language` is a Whisper code like "es"
        or None for auto-detect; `detected_lang` is that same code when
        forced, or the language mlx-whisper actually detected otherwise.
        `initial_prompt` is an optional string of custom vocabulary (names,
        jargon) that biases decoding toward those words/spellings without
        any fine-tuning.

        On auto-detect, the audio is split on pauses and each phrase is
        detected and transcribed independently, so a recording that mixes
        English and Spanish keeps each part in the language it was actually
        spoken. Forcing a specific language skips this and does a single
        pass in that language.
        """
        if self.model is None:
            self.load()

        if isinstance(audio, str):
            audio = load_audio_file(audio)

        prompt = initial_prompt.strip() if initial_prompt else None

        if language is None:
            segments = self._vad_segments(audio)
            if segments and len(segments) > 1:
                parts = []
                detected = None
                for chunk in segments:
                    text, lang = self.transcribe_chunk(
                        chunk, language=None, initial_prompt=prompt,
                        condition_on_previous_text=False,
                    )
                    if text and detected is None:
                        detected = lang
                    if text:
                        parts.append(text)
                return " ".join(parts).strip(), detected

        return self.transcribe_chunk(audio, language=language, initial_prompt=prompt)

    def transcribe_chunk(self, audio, language=None, initial_prompt=None,
                          condition_on_previous_text=True):
        """A single mlx-whisper pass over an already-cut chunk of audio.

        Used both for the final single-segment case and for the live-preview
        per-phrase transcription while still recording. Returns (text, lang).
        """
        import mlx_whisper

        if self.model is None:
            self.load()

        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self.model_name,
            language=language,
            initial_prompt=initial_prompt,
            condition_on_previous_text=condition_on_previous_text,
        )
        return result["text"].strip(), result.get("language", language)

    @property
    def vad_model(self):
        """Lazily-loaded Silero VAD model."""
        if self._vad is None:
            from silero_vad import load_silero_vad

            self._vad = load_silero_vad()
        return self._vad

    def _vad_segments(self, audio):
        """Split audio into per-phrase chunks on silence using Silero VAD.

        Returns a list of float32 numpy chunks (16kHz), or None if VAD is
        unavailable or the audio is too short / has no clear pauses.
        """
        try:
            from silero_vad import get_speech_timestamps
        except Exception:
            return None

        arr = load_audio_file(audio) if isinstance(audio, str) else audio
        if arr is None or len(arr) < 16000:  # under ~1s: not worth splitting
            return None

        timestamps = get_speech_timestamps(
            arr,
            self.vad_model,
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
