"""Simple Streamlit UI for the ASR benchmark.

Two tabs:
  - Grabar: record a clip in the browser, run it through every selected
    backend, see the transcripts side by side.
  - Cargar archivos: upload one or more WAVs and do the same in bulk.

Models are cached per Streamlit session (st.cache_resource) so they load
once and stay warm across recordings/uploads instead of reloading every run.

Run with:  streamlit run ui.py
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
import time
import wave

import streamlit as st

from audio_utils import normalize_to_wav
from backends import ALL_BACKENDS
from metrics import compute_wer
from storage import load_all_results, save_results

st.set_page_config(page_title="Lyrebird ASR Benchmark", layout="wide")

RECORDINGS_DIR = "recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)


@st.cache_resource(show_spinner=False)
def get_backend(backend_id: str):
    backend = ALL_BACKENDS[backend_id]()
    backend.load()
    return backend


def wav_duration_seconds(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        return wf.getnframes() / float(wf.getframerate())


def run_backends(audio_path: str, backend_ids: list[str], expected_text: str | None, on_progress=None):
    # Decode once (handles .opus/.ogg/.mp3/.m4a/.flac too, same decoder the
    # production app uses) so every backend transcribes byte-identical audio.
    wav_path = normalize_to_wav(audio_path)
    try:
        rows = _run_backends_on_wav(wav_path, backend_ids, expected_text, on_progress)
    finally:
        os.unlink(wav_path)
    return rows


def _run_backends_on_wav(audio_path: str, backend_ids: list[str], expected_text: str | None, on_progress=None):
    rows = []
    for backend_id in backend_ids:
        row = {"backend": backend_id, "time_s": None, "text": "", "wer": None, "error": None}
        already_cached = backend_id in st.session_state.get("_loaded_backends", set())
        try:
            if on_progress:
                on_progress(backend_id, "loading" if already_cached else "loading_cold")
            backend = get_backend(backend_id)
            st.session_state.setdefault("_loaded_backends", set()).add(backend_id)

            if on_progress:
                on_progress(backend_id, "transcribing")
            t0 = time.perf_counter()
            text = backend.transcribe(audio_path)
            row["time_s"] = time.perf_counter() - t0
            row["text"] = text
            if expected_text:
                row["wer"] = compute_wer(expected_text, text).wer
            if on_progress:
                on_progress(backend_id, "done")
        except Exception as exc:  # noqa: BLE001
            row["error"] = str(exc)
            if on_progress:
                on_progress(backend_id, "error")
        rows.append(row)
    return rows


def persist(rows, audio_name, source, expected_text):
    """Write this run to results/ so it survives a browser refresh."""
    enriched = [
        dict(r, audio=audio_name, source=source, expected=expected_text, timestamp=time.time())
        for r in rows
    ]
    save_results(enriched, tag=source)


def render_results(rows):
    if not rows:
        return

    valid = [r for r in rows if r["error"] is None]
    fastest = min(valid, key=lambda r: r["time_s"]) if valid else None
    scored = [r for r in valid if r["wer"] is not None]
    best_match = min(scored, key=lambda r: r["wer"]) if scored else None

    if fastest:
        st.caption(f"🥇 Más rápido: **{fastest['backend']}** ({fastest['time_s']:.2f}s)")
    if best_match:
        st.caption(f"🎯 Mejor WER: **{best_match['backend']}** ({best_match['wer'] * 100:.1f}%)")

    for r in rows:
        cols = st.columns([2, 1, 1, 5])
        cols[0].markdown(f"**{r['backend']}**")
        if r["error"]:
            cols[3].error(r["error"])
            continue
        cols[1].write(f"{r['time_s']:.2f}s")
        cols[2].write(f"{r['wer'] * 100:.1f}%" if r["wer"] is not None else "-")
        cols[3].write(r["text"] or "_(vacío)_")


st.title("Lyrebird ASR Benchmark")

available_ids = list(ALL_BACKENDS.keys())
selected_backends = st.multiselect(
    "Backends a probar", available_ids, default=available_ids
)

tab_record, tab_upload, tab_history = st.tabs(
    ["🎙️ Grabar", "📁 Cargar archivos", "📊 Historial"]
)

PROGRESS_LABELS = {
    "loading_cold": "cargando {} (primera vez — puede descargar el modelo, tarda más)",
    "loading": "cargando {} en memoria",
    "transcribing": "transcribiendo con {}",
    "done": "{} listo",
    "error": "{} falló",
}

with tab_record:
    st.write(
        "Grabá una frase: en cuanto cortás la grabación se corre el benchmark solo, "
        "sin tocar ningún botón."
    )
    st.caption(
        "Esto es 'apenas termino de grabar, tengo el resultado' — no transcripción en "
        "vivo palabra por palabra mientras hablás. Eso requeriría streaming real, y solo "
        "algunos motores (parakeet) lo soportan bien; comparar 4 modelos en ese modo no "
        "sería una prueba pareja."
    )
    expected = st.text_input("Texto esperado (opcional, para calcular WER)", key="expected_record")
    audio_value = st.audio_input("Grabá tu frase")
    audio_bytes = audio_value.getvalue() if audio_value is not None else None

    if audio_bytes:
        duration = wav_duration_seconds(audio_bytes)
        if duration < 0.3:
            st.warning(
                f"⚠️ Se grabaron solo {duration:.2f}s. Es probable que el micrófono no haya "
                "capturado nada (permiso de micrófono del navegador, o dispositivo "
                "equivocado). Probá grabar de nuevo antes de confiar en el resultado."
            )
        else:
            st.success(f"🎙️ Grabado: {duration:.1f}s de audio.")

        clip_hash = hashlib.md5(audio_bytes).hexdigest()

        if not selected_backends:
            st.warning("Elegí al menos un backend arriba.")
        elif st.session_state.get("last_clip_hash") == clip_hash:
            # Same recording as last rerun (e.g. just typed in the text box
            # above) — don't re-run the benchmark, show the cached result.
            render_results(st.session_state.get("last_clip_rows", []))
        else:
            clip_path = os.path.join(RECORDINGS_DIR, f"clip-{int(time.time())}.wav")
            with open(clip_path, "wb") as f:
                f.write(audio_bytes)
            if expected:
                with open(os.path.splitext(clip_path)[0] + ".txt", "w", encoding="utf-8") as f:
                    f.write(expected)

            with st.status("Procesando grabación...", expanded=True) as status:
                def _progress(name, phase):
                    status.write(PROGRESS_LABELS[phase].format(name))

                rows = run_backends(
                    clip_path, selected_backends, expected or None, on_progress=_progress
                )
                status.update(label="✅ Listo", state="complete")

            persist(rows, os.path.basename(clip_path), "record", expected or None)
            st.session_state["last_clip_hash"] = clip_hash
            st.session_state["last_clip_rows"] = rows
            render_results(rows)

        if st.button("Volver a correr", key="rerun_record"):
            st.session_state.pop("last_clip_hash", None)
            st.rerun()

UPLOAD_TYPES = ["wav", "opus", "ogg", "mp3", "m4a", "flac"]

with tab_upload:
    st.write("Subí uno o más audios y corré todos los backends sobre cada uno.")
    uploaded_files = st.file_uploader(
        "Archivos de audio", type=UPLOAD_TYPES, accept_multiple_files=True
    )
    expected_bulk = st.text_area(
        "Texto esperado (opcional). Si subís varios archivos, se aplica solo cuando subís uno solo.",
        key="expected_upload",
    )

    if uploaded_files and st.button("Correr benchmark", key="run_upload"):
        if not selected_backends:
            st.warning("Elegí al menos un backend arriba.")
        else:
            single_file = len(uploaded_files) == 1
            for uf in uploaded_files:
                st.subheader(uf.name)
                suffix = os.path.splitext(uf.name)[1] or ".wav"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(uf.getvalue())
                    tmp_path = tmp.name
                try:
                    exp = expected_bulk.strip() if (single_file and expected_bulk.strip()) else None
                    with st.status(f"Procesando {uf.name}...", expanded=True) as status:
                        def _progress(name, phase):
                            status.write(PROGRESS_LABELS[phase].format(name))

                        rows = run_backends(
                            tmp_path, selected_backends, exp, on_progress=_progress
                        )
                        status.update(label="✅ Listo", state="complete")
                    persist(rows, uf.name, "upload", exp)
                    render_results(rows)
                finally:
                    os.unlink(tmp_path)

with tab_history:
    st.write(
        "Todas las corridas se guardan en `results/` apenas terminan, así que "
        "sobreviven a un refresh de la página o a cerrar la app."
    )
    if st.button("Recargar historial", key="reload_history"):
        st.rerun()

    history_rows = load_all_results()
    if not history_rows:
        st.info("Todavía no hay corridas guardadas.")
    else:
        st.dataframe(
            history_rows,
            column_order=[
                "_run", "source", "audio", "backend", "time_s", "wer", "error", "text", "expected",
            ],
        )
