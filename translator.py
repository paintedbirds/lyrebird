"""Offline ES<->EN translation for the "translate result" pill action.

Wraps argostranslate, which runs a small local MT model per language pair
(no network calls after the pair is installed once). Only the ES<->EN pair
is used today, matching the pill's language toggle.
"""

import threading

_lock = threading.Lock()
_installed_pairs = set()


def translate(text, from_code, to_code):
    """Translate `text` from `from_code` to `to_code` (e.g. "es" -> "en")."""
    import argostranslate.translate

    _ensure_package(from_code, to_code)
    return argostranslate.translate.translate(text, from_code, to_code)


def _ensure_package(from_code, to_code):
    """Install the argos-translate package for this language pair if it's
    not already on disk. Downloads once, from Argos's package index."""
    pair = (from_code, to_code)
    if pair in _installed_pairs:
        return

    import argostranslate.package

    with _lock:
        if pair in _installed_pairs:
            return
        installed = argostranslate.package.get_installed_packages()
        if any(p.from_code == from_code and p.to_code == to_code for p in installed):
            _installed_pairs.add(pair)
            return

        argostranslate.package.update_package_index()
        available = argostranslate.package.get_available_packages()
        match = next(
            (p for p in available if p.from_code == from_code and p.to_code == to_code),
            None,
        )
        if match is None:
            raise RuntimeError("No argos-translate package for %s -> %s" % pair)
        path = match.download()
        argostranslate.package.install_from_path(path)
        _installed_pairs.add(pair)
