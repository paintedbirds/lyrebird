# Handoff: Lyrebird landing page

## What this is
A standalone marketing landing page for **Lyrebird** (the menu-bar speech-to-text
app in the parent folder `~/whisper-menubar`). Lives in its own subfolder,
`~/whisper-menubar/landing/`, separate from the app's source code.

Plain HTML/CSS/JS. No build step, no frameworks, no web fonts, no images.
Open `index.html` directly in a browser (double-click it) — no server needed.

## Files
- `index.html` (179 lines) — markup, 3 sections only: nav, hero, features, footer
- `styles.css` (414 lines) — all styling, dark theme, CSS-only animations
- `script.js` (104 lines) — scroll-reveal (IntersectionObserver) + the hero typing demo

## Design brief (from the user)
- Copy the clean/simple pattern of Apple's site + the structure of competitor
  Superwhisper (superwhisper.com), but **shorter**: just hero → features → footer,
  no pricing/FAQ/testimonials.
- Must clearly communicate **Mac-only** (no Windows/Linux).
- Strong but simple motion, good performance, with a "transcription vibes" feel.

## How that was implemented
- **Dark theme**, system font stack only (`-apple-system` etc.) — zero network
  requests for fonts, matches both Apple's and Superwhisper's look.
- **Hero**: animated CSS-only waveform (10 bars, staggered `scaleY` keyframes)
  inside a floating "pill" that mimics the app's real recording pill (✓ / ✕
  buttons), with a JS typewriter below it that types one line in English, then
  one in Spanish, in a loop — this directly demonstrates the app's bilingual
  auto-detect feature instead of just claiming it.
- **Mac-only messaging**: a "for Mac" badge in the nav pill, plus a dedicated
  feature card ("Built for Mac. Only Mac.") — no Apple logo glyph is used
  anywhere (avoided for trademark reasons); a generic macOS-window icon (three
  dots, like traffic-light buttons) stands in for "native Mac app" instead.
- **Motion**: `IntersectionObserver`-driven fade-up reveals on scroll, all
  animations are CSS transforms (GPU-cheap), and everything respects
  `prefers-reduced-motion: reduce`.
- **No dead CTA**: there's no real public download yet, so the hero button
  "Get Lyrebird for Mac" smooth-scrolls to the footer, which says the app is
  "currently in private beta" and links a `mailto:` to
  painted.birds.software@gmail.com instead of a fake download link.

## Feature copy — sourced from the actual repo, not invented
Pulled from `README.md`, `transcriber.py`, `hotkey.py`, `store.py`,
`audio_recorder.py` in the parent folder:
1. Runs entirely on-device (local Whisper, no internet/API keys)
2. One tap from anywhere (menu bar click or global hotkey `⇧⌘L`, no
   Accessibility permission needed — uses Carbon `RegisterEventHotKey`)
3. Auto-copies every transcription to the clipboard
4. Bilingual EN/ES auto-detect (Silero VAD splits speech on pauses so each
   phrase is transcribed in its own language)
5. Transcribes dropped-in files too (WhatsApp voice notes, MP3, WAV, M4A, etc.)
6. Native AppKit app, no Electron, no Dock icon, 5 selectable Whisper models

Footer copyright line matches the license in the main `README.md` exactly:
"© 2026 Painted Bird."

## Verification done
- `node --check script.js` → passes
- CSS brace count balanced (78 open / 78 close)
- `index.html` parsed cleanly with Python's `html.parser` (no malformed tags)
- **Not done**: no actual browser/visual screenshot check (sandbox has no
  headless browser available). Worth opening it for a real look before calling
  it final.

## Open items / what's not done yet
- `landing/` is **not committed** to git yet. `git status` also shows
  unrelated uncommitted changes from earlier work: `app.py` and `build_app.sh`
  modified, plus an untracked `icon-menubar.svg` — none of that was touched in
  this landing-page task, just flagging it's sitting there uncommitted.
- No real screenshot/video of the actual running app is used anywhere; the
  hero visual is a stylized re-creation, not a capture of the real UI.
- If the look needs to go lighter (Apple-style white) instead of dark
  (Superwhisper-style), that's a CSS variable swap in `styles.css` (`:root`),
  not a rewrite.

## Unrelated open threads in this project (FYI, not part of this task)
- Local git repo has commits up to `f13efc6` but has never been pushed
  anywhere — pushing to a private GitHub repo under the "Painted Birds" org
  was blocked earlier because the `gh` CLI couldn't be installed in the
  sandbox (network allowlist + no sudo). Still needs a path forward (user
  pushing it themselves is the simplest fix).
- `build_app.sh` was rewritten to fix two things: the Finder/Spotlight-launch
  menu-bar-icon bug (macOS 26 bug, FB21015611) and Activity Monitor showing
  "Python" instead of "Lyrebird". Whether re-running `rebuild_app.command` and
  testing from Spotlight actually confirmed both fixes work has not been
  verified back from the user yet.
