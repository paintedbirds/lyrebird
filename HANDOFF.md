# Lyrebird — Hand-off para continuar

## Qué es
App local de speech-to-text para macOS, 100% offline, con OpenAI Whisper.
Vive en la barra de menú (accessory app, sin Dock). Carpeta: `~/whisper-menubar`.
Venv: `~/whisper-menubar/.venv`. Python 3.12 (Homebrew).

## Cómo correr / probar
```bash
cd ~/whisper-menubar
# matar instancias y arrancar limpio:
pkill -9 -f "app.py"; rm -f /tmp/lyrebird.pid /tmp/lyrebird.log; rm -rf __pycache__
.venv/bin/python app.py >/tmp/lyrebird.log 2>&1 &
# ver diagnostico:
cat /tmp/lyrebird.log
```
App bundle para Finder/Spotlight: `~/Applications/Lyrebird.app`.
Reconstruir bundle: `~/whisper-menubar/build_app.sh` (genera AppIcon.icns con make_icon.py).
NOTA: el sandbox del agente mata procesos en background al terminar la tool call,
así que para ver la barra de menu real hay que lanzar desde Finder (sesion grafica del usuario).

## Archivos
- `app.py` — app AppKit/PyObjC: NSStatusItem, pill flotante (NSPanel), settings, history, hotkey
- `transcriber.py` — Whisper + Silero VAD (split bilingue EN/ES por frase en auto-detect). Envuelto en `torch.no_grad()`
- `audio_recorder.py` — sounddevice 16kHz mono + nivel RMS para waveform
- `store.py` — config JSON en `~/Library/Application Support/Lyrebird/config.json` (migra del viejo WhisperMenuBar)
- `hotkey.py` — hotkey global Cmd+Shift+L via Carbon RegisterEventHotKey (sin permiso Accessibility)
- `make_icon.py` / `build_app.sh` / `run.sh`
- `fonts/Arimo.ttf`, `AppIcon.icns`

## Lo que YA funciona
- Transcripcion bilingue (VAD por frase)
- Fix crash PyTorch SIGABRT: `torch.set_grad_enabled(False)` + `torch.no_grad()` + `os._exit(0)` al salir
- Hotkey global Cmd+Shift+L (probado: register() devuelve True). Toggle listen desde cualquier app
- Instancia unica: lock file `/tmp/lyrebird.pid` (segunda apertura sale sola). Probado OK
- Bundle `.app` con icono mic azul en Spotlight, nombre "Lyrebird"
- Pill de confirmacion al arrancar: "Lyrebird listo · ⇧⌘L"

## PROBLEMA ABIERTO (lo que estamos debuggeando)
El ICONO de la barra de menu NO aparece de forma consistente. El usuario lo vio
aparecer "por un segundo" durante relaunches, luego desaparece.

Sintomas del log (sesion real del usuario, screens=1, NO es notch ni monitor):
```
[Lyrebird] status item created; button window frame x=0 y=0 w=64 h=0 visible=True
[Lyrebird] post-layout: button window x=0 y=0 w=64 h=0 hasImage=True itemLen=48 visible=True
```
`button.window().frame()` da altura 0 aun post-layout. visible=True pero no se dibuja.
Incluso con texto fijo "LYRE" (diagnostico) no aparecia → no es problema de render de imagen.

Descartado:
- Notch / barra llena: hay espacio de sobra (confirmado por screenshot computer-use)
- Monitor secundario: screens=1
- Multiples instancias zombi: ya hay guard de instancia unica

computer-use NO sirve para ver el icono: la app corre como proceso "Python" que no es
otorgable en request_access, y el filtro nativo de screenshot lo oculta de la captura.

## ULTIMO CAMBIO (sin probar todavia)
Hipotesis actual: el status item se crea DEMASIADO TEMPRANO (en setup(), antes de que
el run loop arranque), lo que lo hace renderizar de forma intermitente.

Fix aplicado en `app.py` (NO testeado aun por el usuario desde Finder):
- `setup()` ya NO crea el status item; solo pill, hotkey, model thread
- Agregado `applicationDidFinishLaunching_(self, notification)` que llama
  `_build_status_item()` + `_startup_hello()` DESPUES de que arranca el loop
- `_build_status_item` restaurado al icono mic.fill (size 17x17, template) con log de diagnostico

## PROXIMO PASO
1. Usuario abre `~/Applications/Lyrebird.app` desde Finder (o `cd ~/whisper-menubar && .venv/bin/python app.py`)
2. Leer `/tmp/lyrebird.log` → si la nueva linea "status item (didFinishLaunching)" da h>0, deberia verse el icono
3. Si SIGUE sin aparecer con h=0:
   - Probar crear el NSStatusItem y retener fuerte el button; revisar si PyObjC lo libera
   - Probar `NSApp.activateIgnoringOtherApps_(True)` antes de crear el item
   - Alternativa: empaquetar de verdad con py2app (da bundle con su propio proceso, no "Python",
     resuelve tambien el prompt de microfono que dice "python3.12" y permitiria ver el item via computer-use)
4. Si funciona: quitar las lineas de print de diagnostico de `_build_status_item` y reconstruir el bundle

## Pendientes menores
- Icono custom abstracto (pajaro + mic/voz) — el usuario pidio un prompt, ya se le dio. Cuando tenga
  el PNG 1024x1024, cablear en make_icon.py en vez del SF Symbol
- El prompt de permiso de microfono dice "python3.12" (cosmetico, inevitable sin py2app)
