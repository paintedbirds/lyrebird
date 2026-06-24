"""Whisper Menu Bar - 100% local speech-to-text for macOS.

Tap the menu bar icon to start listening; a floating pill stays pinned on top
while you keep working. Click the check to finish (transcribe + auto-copy) or
the X to cancel. Right-click the icon for Settings, History, file transcription,
and Quit. Everything runs locally via OpenAI Whisper.

Built natively with AppKit/PyObjC so the menu bar item, the pill, and the
settings window share one Cocoa event loop.

Run with:  python app.py
"""

import math
import os
import threading

# PyTorch on macOS can SIGABRT from duplicate OpenMP runtimes / heavy threading.
# Set before torch is imported (it loads lazily during transcription).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import objc
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize, NSObject, NSTimer
from PyObjCTools import AppHelper
from AppKit import (
    NSAppearance,
    NSAppearanceNameDarkAqua,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSBoldFontMask,
    NSButton,
    NSColor,
    NSCompositingOperationSourceAtop,
    NSCompositingOperationSourceOver,
    NSFontManager,
    NSImageSymbolConfiguration,
    NSRectFillUsingOperation,
    NSControlSizeSmall,
    NSEventMaskLeftMouseUp,
    NSEventMaskRightMouseUp,
    NSEventModifierFlagControl,
    NSEventTypeRightMouseUp,
    NSFont,
    NSImage,
    NSImageOnly,
    NSMenu,
    NSMenuItem,
    NSModalResponseOK,
    NSOpenPanel,
    NSPanel,
    NSPasteboard,
    NSPasteboardTypeString,
    NSPopUpButton,
    NSProgressIndicator,
    NSScreen,
    NSStatusBar,
    NSStatusWindowLevel,
    NSTextAlignmentLeft,
    NSTextField,
    NSVariableStatusItemLength,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectMaterialWindowBackground,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskNonactivatingPanel,
    NSWindowStyleMaskTitled,
)

from Quartz import CALayer

from audio_recorder import Recorder, list_input_devices
from store import Store
from transcriber import LANGUAGES, Transcriber

LANG_MAP = {label: code for label, code in LANGUAGES}
CODE_TO_LABEL = {code: label for label, code in LANGUAGES}
MODELS = ["tiny", "base", "small", "medium", "large-v3"]
ALLOWED_TYPES = ["opus", "mp3", "wav", "m4a", "mp4", "aac", "flac", "ogg", "mov", "amr", "3gp"]
DEFAULT_MIC = "System default"

PILL_W, PILL_H = 320, 52


def accent_blue(alpha=1.0):
    """Vibrant macOS-style blue used across the UI."""
    return NSColor.colorWithSRGBRed_green_blue_alpha_(0.20, 0.55, 1.0, alpha)


def wave_blue():
    """Brighter blue for the animated waveform on the dark glass."""
    return NSColor.colorWithSRGBRed_green_blue_alpha_(0.40, 0.70, 1.0, 0.95)


FONT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Arimo.ttf")
FONT_FAMILY = "Arimo"
# (NSFontManager weight, traits) per logical weight name.
_WEIGHTS = {"regular": (5, 0), "medium": (6, 0), "bold": (9, NSBoldFontMask)}


def _register_fonts():
    """Register the bundled font for this process only (no system install)."""
    try:
        from CoreText import (
            CTFontManagerRegisterFontsForURL,
            kCTFontManagerScopeProcess,
        )
        from Foundation import NSURL

        if os.path.exists(FONT_PATH):
            CTFontManagerRegisterFontsForURL(
                NSURL.fileURLWithPath_(FONT_PATH), kCTFontManagerScopeProcess, None
            )
    except Exception:
        pass


_register_fonts()


def ui_font(size, weight="regular"):
    """Arimo at the requested weight, falling back to the system font."""
    w, traits = _WEIGHTS.get(weight, (5, 0))
    f = NSFontManager.sharedFontManager().fontWithFamily_traits_weight_size_(
        FONT_FAMILY, traits, w, size
    )
    if f is not None:
        return f
    return NSFont.boldSystemFontOfSize_(size) if weight == "bold" else NSFont.systemFontOfSize_(size)


class WaveformView(NSView):
    """Animated waveform bars driven by the live mic level."""

    def initWithFrame_(self, frame):
        self = objc.super(WaveformView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.level = 0.0
        self.phase = 0.0
        return self

    def drawRect_(self, rect):
        bounds = self.bounds()
        n = 5
        bar_w, gap = 3.0, 3.0
        total = n * bar_w + (n - 1) * gap
        x = (bounds.size.width - total) / 2.0
        cy = bounds.size.height / 2.0
        wave_blue().set()
        for i in range(n):
            osc = 0.5 + 0.5 * math.sin(self.phase * 2.0 + i * 0.9)
            h = 4.0 + (bounds.size.height - 8.0) * (0.22 + 0.78 * self.level) * osc
            bar = NSMakeRect(x, cy - h / 2.0, bar_w, h)
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bar, bar_w / 2.0, bar_w / 2.0
            ).fill()
            x += bar_w + gap


class AppController(NSObject):
    """Owns the status item, the floating pill, settings, and the flow."""

    @objc.python_method
    def setup(self, store, transcriber, recorder):
        self.store = store
        self.transcriber = transcriber
        self.recorder = recorder
        self.recorder.set_device(store.get("device"))
        self.modelReady = False
        self.state = "idle"  # idle | listening | transcribing
        self.language = store.get("language")
        self.auto_copy = store.get("auto_copy")
        self.waveTimer = None
        self.settingsWindow = None
        self.settingsStatus = None
        self._build_pill()
        self._register_hotkey()
        threading.Thread(target=self._load_model_thread, daemon=True).start()
        # The status item and confirmation flash are created in
        # applicationDidFinishLaunching_, after the run loop is up; creating the
        # status item before launch finishes makes it intermittently not render.

    def applicationDidFinishLaunching_(self, notification):
        self._build_status_item()
        self._startup_hello()

    @objc.python_method
    def _startup_hello(self):
        self.statusLabel.setStringValue_("Lyrebird listo · ⇧⌘L")
        self.waveform.setHidden_(True)
        self.spinner.setHidden_(True)
        self.cancelButton.setHidden_(True)
        self.doneButton.setHidden_(True)
        self._show_pill()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.2, self, "autoHide:", None, False
        )

    @objc.python_method
    def _register_hotkey(self):
        """Cmd+Shift+L from anywhere starts/stops listening (Carbon hotkey,
        no Accessibility permission needed)."""
        try:
            import hotkey

            hotkey.register(
                lambda: AppHelper.callAfter(self.toggleListen_, None)
            )
        except Exception:
            pass

    @objc.python_method
    def _build_main_menu(self):
        """App menu so the Dock app supports Cmd+L (listen) and Cmd+Q (quit)."""
        main = NSMenu.alloc().init()
        app_item = NSMenuItem.alloc().init()
        main.addItem_(app_item)
        app_menu = NSMenu.alloc().init()
        for title, action, key in (
            ("Start / Stop Listening", "toggleListen:", "l"),
            ("Settings…", "showSettings:", ","),
        ):
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
            it.setTarget_(self)
            app_menu.addItem_(it)
        app_menu.addItem_(NSMenuItem.separatorItem())
        quit_it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Lyrebird", "quitApp:", "q"
        )
        quit_it.setTarget_(self)
        app_menu.addItem_(quit_it)
        app_item.setSubmenu_(app_menu)
        NSApplication.sharedApplication().setMainMenu_(main)

    @objc.python_method
    def _set_dock_icon(self):
        """Blue mic Dock icon instead of the generic Python rocket."""
        try:
            base = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "mic.circle.fill", "Lyrebird"
            )
            if base is None:
                return
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(220, 6, 3)
            base = base.imageWithSymbolConfiguration_(cfg)
            size = base.size()
            icon = NSImage.alloc().initWithSize_(size)
            icon.lockFocus()
            r = NSMakeRect(0, 0, size.width, size.height)
            base.drawInRect_fromRect_operation_fraction_(
                r, NSMakeRect(0, 0, 0, 0), NSCompositingOperationSourceOver, 1.0
            )
            accent_blue(1.0).set()
            NSRectFillUsingOperation(r, NSCompositingOperationSourceAtop)
            icon.unlockFocus()
            NSApplication.sharedApplication().setApplicationIconImage_(icon)
        except Exception:
            pass

    # ------------------------------------------------------- status item
    @objc.python_method
    def _build_status_item(self):
        self.statusItem = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.statusItem.setVisible_(True)
        button = self.statusItem.button()
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "mic.fill", "Lyrebird"
        )
        if img is not None:
            img.setSize_(NSMakeSize(17, 17))
            img.setTemplate_(True)
            button.setImage_(img)
            button.setImagePosition_(NSImageOnly)
        else:
            button.setTitle_("\U0001f399")
        button.setToolTip_("Lyrebird · ⇧⌘L")
        button.setTarget_(self)
        button.setAction_("statusClicked:")
        button.sendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)

    @objc.python_method
    def _build_menu(self):
        menu = NSMenu.alloc().init()

        lang_menu = NSMenu.alloc().init()
        for label, code in LANGUAGES:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                label, "setLanguage:", ""
            )
            item.setTarget_(self)
            item.setRepresentedObject_(label)
            if code == self.language:
                item.setState_(1)
            lang_menu.addItem_(item)
        lang_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Language", None, ""
        )
        lang_item.setSubmenu_(lang_menu)
        menu.addItem_(lang_item)

        hist_menu = NSMenu.alloc().init()
        history = self.store.history()
        if history:
            for entry in history:
                preview = " ".join(entry.get("text", "").split())
                if len(preview) > 50:
                    preview = preview[:47] + "…"
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    preview, "copyHistory:", ""
                )
                item.setTarget_(self)
                item.setRepresentedObject_(entry.get("text", ""))
                hist_menu.addItem_(item)
            hist_menu.addItem_(NSMenuItem.separatorItem())
            clear = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Clear history", "clearHistory:", ""
            )
            clear.setTarget_(self)
            hist_menu.addItem_(clear)
        else:
            empty = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "No history yet", None, ""
            )
            empty.setEnabled_(False)
            hist_menu.addItem_(empty)
        hist_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "History (last 5)", None, ""
        )
        hist_item.setSubmenu_(hist_menu)
        menu.addItem_(hist_item)

        menu.addItem_(NSMenuItem.separatorItem())
        for title, action in (
            ("Settings…", "showSettings:"),
            ("Transcribe file…", "chooseFile:"),
        ):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            item.setTarget_(self)
            menu.addItem_(item)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Lyrebird", "quitApp:", "q"
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self.menu = menu

    # --------------------------------------------------------- pill UI
    @objc.python_method
    def _circle_button(self, frame, symbol, action, bg, tint):
        b = NSButton.alloc().initWithFrame_(frame)
        b.setBordered_(False)
        b.setTitle_("")
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, symbol)
        if img is not None:
            b.setImage_(img)
            b.setImagePosition_(NSImageOnly)
        b.setContentTintColor_(tint)
        b.setWantsLayer_(True)
        b.layer().setBackgroundColor_(bg.CGColor())
        b.layer().setCornerRadius_(frame.size.height / 2.0)
        b.setTarget_(self)
        b.setAction_(action)
        return b

    @objc.python_method
    def _build_pill(self):
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, PILL_W, PILL_H),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSStatusWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setMovableByWindowBackground_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        content = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, PILL_W, PILL_H)
        )
        content.setMaterial_(NSVisualEffectMaterialHUDWindow)
        content.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        content.setState_(NSVisualEffectStateActive)
        content.setAppearance_(NSAppearance.appearanceNamed_(NSAppearanceNameDarkAqua))
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(PILL_H / 2.0)
        content.layer().setMasksToBounds_(True)
        content.layer().setBorderWidth_(1.0)
        content.layer().setBorderColor_(accent_blue(0.55).CGColor())
        panel.setContentView_(content)

        # Vibrant blue tint over the frosted glass (a sublayer, so it doesn't
        # intercept clicks or block window dragging).
        tint = CALayer.layer()
        tint.setFrame_(NSMakeRect(0, 0, PILL_W, PILL_H))
        tint.setBackgroundColor_(accent_blue(0.18).CGColor())
        content.layer().addSublayer_(tint)

        self.cancelButton = self._circle_button(
            NSMakeRect(9, 9, 34, 34), "xmark", "cancelClicked:",
            NSColor.colorWithCalibratedWhite_alpha_(0.22, 1.0), NSColor.whiteColor(),
        )
        content.addSubview_(self.cancelButton)

        self.doneButton = self._circle_button(
            NSMakeRect(PILL_W - 9 - 34, 9, 34, 34), "checkmark", "doneClicked:",
            accent_blue(1.0), NSColor.whiteColor(),
        )
        content.addSubview_(self.doneButton)

        self.waveform = WaveformView.alloc().initWithFrame_(NSMakeRect(104, 14, 32, 24))
        content.addSubview_(self.waveform)

        self.spinner = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(108, 16, 20, 20))
        self.spinner.setStyle_(1)
        self.spinner.setControlSize_(NSControlSizeSmall)
        self.spinner.setDisplayedWhenStopped_(False)
        self.spinner.setHidden_(True)
        content.addSubview_(self.spinner)

        self.statusLabel = NSTextField.labelWithString_("Listening")
        self.statusLabel.setFrame_(NSMakeRect(144, 16, 120, 20))
        self.statusLabel.setAlignment_(NSTextAlignmentLeft)
        self.statusLabel.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(0.96, 1.0))
        self.statusLabel.setFont_(ui_font(14, "medium"))
        content.addSubview_(self.statusLabel)

        self.panel = panel

    @objc.python_method
    def _show_pill(self):
        scr = NSScreen.mainScreen().frame()
        x = scr.origin.x + (scr.size.width - PILL_W) / 2.0
        y = scr.origin.y + scr.size.height - PILL_H - 64
        self.panel.setFrameOrigin_(NSMakePoint(x, y))
        self.panel.orderFrontRegardless()

    @objc.python_method
    def _hide_pill(self):
        self.panel.orderOut_(None)

    @objc.python_method
    def _set_pill_state(self, st):
        listening = st == "listening"
        transcribing = st == "transcribing"
        self.waveform.setHidden_(not listening)
        self.spinner.setHidden_(not transcribing)
        if transcribing:
            self.spinner.startAnimation_(None)
        else:
            self.spinner.stopAnimation_(None)
        self.cancelButton.setHidden_(not listening)
        self.doneButton.setHidden_(not listening)
        self.statusLabel.setStringValue_(
            {"listening": "Listening", "transcribing": "Transcribing…", "done": "Copied ✓"}.get(st, "")
        )

    @objc.python_method
    def _set_mic_active(self, active):
        self.statusItem.button().setContentTintColor_(
            accent_blue(1.0) if active else None
        )

    # ------------------------------------------------------ wave animation
    @objc.python_method
    def _start_wave_timer(self):
        self.waveTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.05, self, "tickWave:", None, True
        )

    @objc.python_method
    def _stop_wave_timer(self):
        if self.waveTimer is not None:
            self.waveTimer.invalidate()
            self.waveTimer = None

    def tickWave_(self, timer):
        self.waveform.level = self.recorder.level
        self.waveform.phase = self.waveform.phase + 0.18
        self.waveform.setNeedsDisplay_(True)

    # ----------------------------------------------------------- flow
    @objc.python_method
    def _start_listening(self):
        if not self.modelReady:
            self._flash("Loading model…")
            return
        try:
            self.recorder.start()
        except Exception:  # noqa: BLE001
            self._flash("Mic error")
            return
        self.state = "listening"
        self._set_mic_active(True)
        self._set_pill_state("listening")
        self._show_pill()
        self._start_wave_timer()

    @objc.python_method
    def _finish_listening(self):
        audio, _wav = self.recorder.stop()
        self._stop_wave_timer()
        self._set_mic_active(False)
        if audio is None or len(audio) == 0:
            self.state = "idle"
            self._hide_pill()
            return
        self.state = "transcribing"
        self._set_pill_state("transcribing")
        threading.Thread(target=self._transcribe_thread, args=(audio,), daemon=True).start()

    @objc.python_method
    def _flash(self, text):
        self.statusLabel.setStringValue_(text)
        self.waveform.setHidden_(True)
        self.spinner.setHidden_(True)
        self.cancelButton.setHidden_(True)
        self.doneButton.setHidden_(True)
        self._show_pill()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.4, self, "autoHide:", None, False
        )

    @objc.python_method
    def _transcribe_thread(self, audio):
        try:
            text = self.transcriber.transcribe(audio, language=self.language)
            AppHelper.callAfter(self._on_transcribed, text or "")
        except Exception as exc:  # noqa: BLE001
            AppHelper.callAfter(self._on_error, str(exc))

    @objc.python_method
    def _on_transcribed(self, text):
        text = text.strip()
        if text:
            self.store.add_history(text)
            if self.auto_copy:
                self._copy_to_clipboard(text)
                self._set_pill_state("done")
            else:
                self._set_pill_state("idle")
                self.statusLabel.setStringValue_("Done")
        else:
            self._set_pill_state("idle")
            self.statusLabel.setStringValue_("No speech")
        self.state = "idle"
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.2, self, "autoHide:", None, False
        )

    @objc.python_method
    def _on_error(self, msg):
        self._set_pill_state("idle")
        self.statusLabel.setStringValue_("Error")
        self.state = "idle"
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.6, self, "autoHide:", None, False
        )

    def autoHide_(self, timer):
        if self.state == "idle":
            self._hide_pill()

    @objc.python_method
    def _copy_to_clipboard(self, text):
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)

    @objc.python_method
    def _load_model_thread(self):
        name = self.transcriber.model_name
        try:
            AppHelper.callAfter(self._set_settings_status, "Loading %s…" % name)
            self.transcriber.load()
            self.modelReady = True
            AppHelper.callAfter(self._set_settings_status, "Model ready: %s" % name)
        except Exception:  # noqa: BLE001
            self.modelReady = False
            AppHelper.callAfter(self._set_settings_status, "Error loading model")

    # --------------------------------------------------------- settings
    @objc.python_method
    def _build_settings(self):
        W, H = 380, 296
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
        )
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False
        )
        win.setTitle_("Lyrebird settings")
        win.setReleasedWhenClosed_(False)
        win.setTitlebarAppearsTransparent_(True)
        win.center()
        win.setDelegate_(self)

        effect = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        effect.setMaterial_(NSVisualEffectMaterialWindowBackground)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        win.setContentView_(effect)
        c = effect

        def label(text, y, w=90):
            lbl = NSTextField.labelWithString_(text)
            lbl.setFrame_(NSMakeRect(20, y, w, 22))
            c.addSubview_(lbl)
            return lbl

        title = NSTextField.labelWithString_("Settings")
        title.setFrame_(NSMakeRect(20, H - 44, 340, 24))
        title.setFont_(NSFont.boldSystemFontOfSize_(15))
        title.setTextColor_(accent_blue(1.0))
        c.addSubview_(title)

        label("Model:", H - 86)
        self.modelPopup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(118, H - 88, 240, 26), False
        )
        self.modelPopup.addItemsWithTitles_(MODELS)
        self.modelPopup.setTarget_(self)
        self.modelPopup.setAction_("modelChanged:")
        c.addSubview_(self.modelPopup)

        label("Language:", H - 124)
        self.langPopup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(118, H - 126, 240, 26), False
        )
        self.langPopup.addItemsWithTitles_([lbl for lbl, _ in LANGUAGES])
        self.langPopup.setTarget_(self)
        self.langPopup.setAction_("settingsLanguageChanged:")
        c.addSubview_(self.langPopup)

        label("Microphone:", H - 162)
        self.micPopup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(118, H - 164, 240, 26), False
        )
        self.micPopup.setTarget_(self)
        self.micPopup.setAction_("micChanged:")
        c.addSubview_(self.micPopup)

        self.autoCopyCheck = NSButton.checkboxWithTitle_target_action_(
            "Copy to clipboard automatically", self, "autoCopyToggled:"
        )
        self.autoCopyCheck.setFrame_(NSMakeRect(20, H - 200, 340, 22))
        c.addSubview_(self.autoCopyCheck)

        note = NSTextField.labelWithString_(
            "Tip: use Auto-detect for mixed English/Spanish."
        )
        note.setFrame_(NSMakeRect(20, H - 234, 340, 18))
        note.setTextColor_(NSColor.secondaryLabelColor())
        note.setFont_(NSFont.systemFontOfSize_(11))
        c.addSubview_(note)

        self.settingsStatus = NSTextField.labelWithString_("")
        self.settingsStatus.setFrame_(NSMakeRect(20, 16, 340, 18))
        self.settingsStatus.setTextColor_(NSColor.secondaryLabelColor())
        self.settingsStatus.setFont_(NSFont.systemFontOfSize_(11))
        c.addSubview_(self.settingsStatus)

        self.settingsWindow = win

    @objc.python_method
    def _refresh_mic_items(self):
        self.micPopup.removeAllItems()
        titles = [DEFAULT_MIC] + [name for _i, name in list_input_devices()]
        self.micPopup.addItemsWithTitles_(titles)
        saved = self.store.get("device")
        self.micPopup.selectItemWithTitle_(saved if saved in titles else DEFAULT_MIC)

    @objc.python_method
    def _sync_settings(self):
        self.modelPopup.selectItemWithTitle_(self.transcriber.model_name)
        self.langPopup.selectItemWithTitle_(CODE_TO_LABEL.get(self.language, LANGUAGES[0][0]))
        self._refresh_mic_items()
        self.autoCopyCheck.setState_(1 if self.auto_copy else 0)
        self._set_settings_status(
            "Model ready: %s" % self.transcriber.model_name
            if self.modelReady
            else "Loading model…"
        )

    @objc.python_method
    def _set_settings_status(self, text):
        if self.settingsStatus is not None:
            self.settingsStatus.setStringValue_(text)

    def showSettings_(self, sender):
        if self.settingsWindow is None:
            self._build_settings()
        self._sync_settings()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.settingsWindow.makeKeyAndOrderFront_(None)

    def modelChanged_(self, sender):
        name = sender.titleOfSelectedItem()
        if name == self.transcriber.model_name and self.modelReady:
            return
        self.store.set("model", name)
        self.modelReady = False
        self.transcriber.model_name = name
        self.transcriber.model = None
        self._set_settings_status("Loading %s… (first use downloads it)" % name)
        threading.Thread(target=self._load_model_thread, daemon=True).start()

    def settingsLanguageChanged_(self, sender):
        self.language = LANG_MAP.get(sender.titleOfSelectedItem())
        self.store.set("language", self.language)

    def micChanged_(self, sender):
        title = sender.titleOfSelectedItem()
        name = None if title == DEFAULT_MIC else title
        self.recorder.set_device(name)
        self.store.set("device", name)

    def autoCopyToggled_(self, sender):
        self.auto_copy = bool(sender.state())
        self.store.set("auto_copy", self.auto_copy)

    def windowShouldClose_(self, sender):
        sender.orderOut_(None)
        return False

    # --------------------------------------------------------- actions
    def statusClicked_(self, sender):
        event = NSApplication.sharedApplication().currentEvent()
        right = event is not None and (
            event.type() == NSEventTypeRightMouseUp
            or bool(event.modifierFlags() & NSEventModifierFlagControl)
        )
        if right:
            self._build_menu()
            NSMenu.popUpContextMenu_withEvent_forView_(
                self.menu, event, self.statusItem.button()
            )
            return
        if self.state == "idle":
            self._start_listening()
        elif self.state == "listening":
            self._finish_listening()

    def doneClicked_(self, sender):
        if self.state == "listening":
            self._finish_listening()

    def toggleListen_(self, sender):
        if self.state == "idle":
            self._start_listening()
        elif self.state == "listening":
            self._finish_listening()

    def cancelClicked_(self, sender):
        if self.state == "listening":
            self.recorder.stop()
            self._stop_wave_timer()
            self._set_mic_active(False)
        self.state = "idle"
        self._hide_pill()

    def setLanguage_(self, sender):
        label = sender.representedObject()
        self.language = LANG_MAP.get(label)
        self.store.set("language", self.language)
        if self.settingsWindow is not None:
            self.langPopup.selectItemWithTitle_(label)

    def copyHistory_(self, sender):
        text = sender.representedObject()
        if not text:
            return
        self._copy_to_clipboard(text)
        self.state = "idle"
        self._set_pill_state("done")
        self._show_pill()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.2, self, "autoHide:", None, False
        )

    def clearHistory_(self, sender):
        self.store.clear_history()

    def chooseFile_(self, sender):
        if self.state != "idle" or not self.modelReady:
            return
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(ALLOWED_TYPES)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        if panel.runModal() == NSModalResponseOK:
            urls = panel.URLs()
            if urls and len(urls) > 0:
                path = urls[0].path()
                self.state = "transcribing"
                self._set_pill_state("transcribing")
                self._show_pill()
                threading.Thread(
                    target=self._transcribe_thread, args=(path,), daemon=True
                ).start()

    def quitApp_(self, sender):
        # Hard-exit: avoids PyTorch's C++ teardown aborting on the way out
        # (which left a stuck "ghost" pill on screen).
        try:
            self._hide_pill()
            if self.settingsWindow is not None:
                self.settingsWindow.orderOut_(None)
        except Exception:
            pass
        os._exit(0)


def _ensure_single_instance():
    """Exit if another Lyrebird is already running, so launching again (from
    Finder, Spotlight, etc.) doesn't pile up zombie processes fighting over the
    menu bar slot. Uses a pid lock file."""
    lock = os.path.join(tempfile.gettempdir(), "lyrebird.pid")
    try:
        with open(lock) as f:
            old = int(f.read().strip())
        if old != os.getpid():
            os.kill(old, 0)  # raises if not running
            print("[Lyrebird] already running (pid %d); exiting." % old, flush=True)
            os._exit(0)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        pass
    except PermissionError:
        os._exit(0)  # running under another user; treat as alive
    try:
        with open(lock, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


if __name__ == "__main__":
    import tempfile

    _ensure_single_instance()
    store = Store()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = AppController.alloc().init()
    controller.setup(store, Transcriber(store.get("model")), Recorder())
    app.setDelegate_(controller)
    AppHelper.runEventLoop()
