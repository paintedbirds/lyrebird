"""Persisted settings and transcription history.

Stored as JSON in ~/Library/Application Support/WhisperMenuBar/config.json so
preferences and recent texts survive restarts.
"""

import json
import os
import threading
import time

APP_DIR = os.path.expanduser("~/Library/Application Support/Lyrebird")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
_OLD_CONFIG = os.path.expanduser("~/Library/Application Support/WhisperMenuBar/config.json")
HISTORY_LIMIT = 5

DEFAULTS = {
    "model": os.environ.get("WHISPER_MODEL", "small"),
    "language": None,        # None = auto-detect
    "device": None,          # None = system default microphone
    "auto_copy": True,
    "history": [],           # list of {"text": str, "ts": float}
}


class Store:
    def __init__(self):
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        try:
            with open(CONFIG_PATH) as f:
                raw = json.load(f)
        except Exception:
            # Migrate from old WhisperMenuBar path on first run
            try:
                with open(_OLD_CONFIG) as f:
                    raw = json.load(f)
            except Exception:
                raw = {}
        data = dict(DEFAULTS)
        for key in DEFAULTS:
            if key in raw:
                data[key] = raw[key]
        return data

    def _save(self):
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with self._lock:
                with open(CONFIG_PATH, "w") as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        self.data[key] = value
        self._save()

    def add_history(self, text):
        entry = {"text": text, "ts": time.time()}
        hist = [entry] + self.data.get("history", [])
        self.data["history"] = hist[:HISTORY_LIMIT]
        self._save()

    def history(self):
        return self.data.get("history", [])

    def clear_history(self):
        self.data["history"] = []
        self._save()
