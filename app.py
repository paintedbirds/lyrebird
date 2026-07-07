"""Lyrebird - 100% local speech-to-text for macOS.

Tap the menu bar icon to start listening; a floating pill stays pinned on top
while you keep working. Click the check to finish (transcribe + auto-copy) or
the X to cancel. Right-click the icon for Settings, History, file transcription,
and Quit. Everything runs on-device.

Built natively with AppKit/PyObjC so the menu bar item, the pill, and the
settings window share one Cocoa event loop.

Run with:  python app.py
"""

import math
import os
import sys
import threading

# PyTorch on macOS can SIGABRT from duplicate OpenMP runtimes / heavy threading.
# Set before torch is imported (it loads lazily during transcription).
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


def _resource_path(*parts):
    """Resolve a bundled data file both in dev and inside a PyInstaller build.

    When frozen, PyInstaller unpacks data files under sys._MEIPASS. In dev we
    fall back to this file's own directory so `python app.py` keeps working.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)

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
    NSCompositingOperationDestinationIn,
    NSCompositingOperationSourceAtop,
    NSCompositingOperationSourceOver,
    NSGradient,
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
    NSImageLeft,
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
    NSTextAlignmentCenter,
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

from Quartz import CABasicAnimation, CAGradientLayer, CALayer

from audio_recorder import Recorder, list_input_devices
from store import Store
from transcriber import LANGUAGES, Transcriber

LANG_MAP = {label: code for label, code in LANGUAGES}
CODE_TO_LABEL = {code: label for label, code in LANGUAGES}
MODELS = ["tiny", "base", "small", "medium", "large-v3"]
ALLOWED_TYPES = ["opus", "mp3", "wav", "m4a", "mp4", "aac", "flac", "ogg", "mov", "amr", "3gp"]
DEFAULT_MIC = "System default"

PILL_W, PILL_H = 320, 52
PILL_W_COMPACT = 196   # done (label + copy fallback button)
PILL_W_MINI = 142      # transcribing (cancel X + small label over gradient)
PILL_H_MINI = 47       # transcribing pill height (~10% under PILL_H)


def accent_blue(alpha=1.0):
    """Vibrant macOS-style blue used across the UI."""
    return NSColor.colorWithSRGBRed_green_blue_alpha_(0.20, 0.55, 1.0, alpha)


def wave_blue():
    """Brighter blue for the animated waveform on the dark glass."""
    return NSColor.colorWithSRGBRed_green_blue_alpha_(0.40, 0.70, 1.0, 0.95)


FONT_PATH = _resource_path("fonts", "Arimo.ttf")
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
        amp = self.level ** 0.55  # perceptual curve: quiet speech still visible
        for i in range(n):
            osc = 0.35 + 0.65 * abs(math.sin(self.phase * 2.0 + i * 0.9))
            h = 3.0 + (bounds.size.height - 6.0) * (0.06 + 0.94 * amp) * osc
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
        self.vocabulary = store.get("vocabulary")
        self.waveTimer = None
        self._tgen = 0  # bumping this discards in-flight transcription results
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
        self.statusLabel.setAlignment_(NSTextAlignmentCenter)
        self.statusLabel.setFrame_(NSMakeRect(0, 14, PILL_W_COMPACT, 22))
        self.waveform.setHidden_(True)
        self.spinner.setHidden_(True)
        self.cancelButton.setHidden_(True)
        self.doneButton.setHidden_(True)
        self.copyButton.setHidden_(True)
        self.cancelMiniButton.setHidden_(True)
        # Resize to compact width
        self.pillContent.setFrame_(NSMakeRect(0, 0, PILL_W_COMPACT, PILL_H))
        self.tintLayer.setFrame_(NSMakeRect(0, 0, PILL_W_COMPACT, PILL_H))
        # Position below the status bar icon instead of screen-center
        btn = self.statusItem.button()
        if btn and btn.window():
            icon_frame = btn.window().frame()
            ix = icon_frame.origin.x + icon_frame.size.width / 2
            iy = icon_frame.origin.y
            x = ix - PILL_W_COMPACT / 2
            y = iy - PILL_H - 6
            self.panel.setFrame_display_animate_(
                NSMakeRect(x, y, PILL_W_COMPACT, PILL_H), True, False
            )
        else:
            self._resize_pill(PILL_W_COMPACT, animate=False)
        self.panel.orderFrontRegardless()
        self._schedule_hide(2.2)

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
            ("Settings…", "openSettings:", ","),
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
    @objc.python_method
    def _load_svg_icon(self, size=16):
        """Load the custom SVG icon at `size` points tall, preserving aspect ratio."""
        svg_path = _resource_path("icon-menubar.svg")
        img = NSImage.alloc().initWithContentsOfFile_(svg_path)
        if img is not None:
            nat = img.size()
            w = round(nat.width / nat.height * size) if nat.height > 0 else size
            img.setSize_(NSMakeSize(w, size))
            return img
        return self._make_gradient_symbol("mic.fill", 17, (0.25, 0.62, 1.00), (0.04, 0.14, 0.52))

    @objc.python_method
    def _make_gradient_symbol(self, name, size, start_rgb, end_rgb):
        """SF Symbol filled with a top-to-bottom gradient. Returns NSImage."""
        sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, name)
        if sym is None:
            return None
        sym.setSize_(NSMakeSize(size, size))

        result = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
        result.lockFocus()

        s_col = NSColor.colorWithSRGBRed_green_blue_alpha_(start_rgb[0], start_rgb[1], start_rgb[2], 1.0)
        e_col = NSColor.colorWithSRGBRed_green_blue_alpha_(end_rgb[0], end_rgb[1], end_rgb[2], 1.0)
        grad = NSGradient.alloc().initWithStartingColor_endingColor_(s_col, e_col)
        grad.drawInRect_angle_(NSMakeRect(0, 0, size, size), 90.0)

        sym.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(0, 0, size, size),
            NSMakeRect(0, 0, 0, 0),
            NSCompositingOperationDestinationIn,
            1.0,
        )

        result.unlockFocus()
        return result

    def _build_status_item(self):
        self.statusItem = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.statusItem.setVisible_(True)
        button = self.statusItem.button()
        img = self._load_svg_icon()
        if img is not None:
            button.setImage_(img)
            button.setImagePosition_(NSImageOnly)
        else:
            button.setTitle_("\U0001f399")
        button.setToolTip_("Lyrebird · ⇧⌘L")
        button.setTarget_(self)
        button.setAction_("statusClicked:")
        button.sendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)

    @objc.python_method
    @objc.python_method
    def _menu_item(self, title, action, key="", symbol=None):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
        item.setTarget_(self)
        if symbol:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, title)
            if img is not None:
                img.setSize_(NSMakeSize(16, 16))
                item.setImage_(img)
        return item

    def _build_menu(self):
        menu = NSMenu.alloc().init()

        # --- Toggle Recording
        toggle = self._menu_item("Toggle Recording", "toggleListen:", "", symbol="waveform")
        menu.addItem_(toggle)

        # --- Transcribe file
        menu.addItem_(self._menu_item("Transcribe File…", "chooseFile:", symbol="doc.badge.waveform"))

        # --- History submenu
        hist_menu = NSMenu.alloc().init()
        history = self.store.history()
        if history:
            for entry in history:
                preview = " ".join(entry.get("text", "").split())
                if len(preview) > 50:
                    preview = preview[:47] + "…"
                hi = self._menu_item(preview, "copyHistory:")
                hi.setRepresentedObject_(entry.get("text", ""))
                hist_menu.addItem_(hi)
            hist_menu.addItem_(NSMenuItem.separatorItem())
            hist_menu.addItem_(self._menu_item("Clear history", "clearHistory:"))
        else:
            empty = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "No history yet", None, ""
            )
            empty.setEnabled_(False)
            hist_menu.addItem_(empty)
        hist_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "History…", None, ""
        )
        hist_icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_("clock.arrow.circlepath", "History")
        if hist_icon is not None:
            hist_icon.setSize_(NSMakeSize(16, 16))
            hist_item.setImage_(hist_icon)
        hist_item.setSubmenu_(hist_menu)
        menu.addItem_(hist_item)

        # --- Settings
        settings_item = self._menu_item("Settings…", "openSettings:", ",", symbol="gearshape")
        settings_item.setKeyEquivalentModifierMask_(1 << 20)  # NSCommandKeyMask
        menu.addItem_(settings_item)

        menu.addItem_(NSMenuItem.separatorItem())

        # --- Microphone submenu (inline)
        devices = [DEFAULT_MIC] + [name for _i, name in list_input_devices()]
        saved_device = self.store.get("device")
        current_mic = saved_device if saved_device in devices else DEFAULT_MIC
        mic_menu = NSMenu.alloc().init()
        for name in devices:
            mi = self._menu_item(name, "setDeviceFromMenu:")
            mi.setRepresentedObject_(name)
            if name == current_mic:
                mi.setState_(1)
            mic_menu.addItem_(mi)
        mic_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            current_mic, None, ""
        )
        mic_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "laptopcomputer", "Microphone"
        )
        if mic_img is not None:
            mic_img.setSize_(NSMakeSize(16, 16))
            mic_item.setImage_(mic_img)
        mic_item.setSubmenu_(mic_menu)
        menu.addItem_(mic_item)
        self.micMenuItem = mic_item

        # --- Language submenu (inline)
        lang_menu = NSMenu.alloc().init()
        current_lang_label = CODE_TO_LABEL.get(self.language, "Auto-detect")
        for label, code in LANGUAGES:
            li = self._menu_item(label, "setLanguage:")
            li.setRepresentedObject_(label)
            if code == self.language:
                li.setState_(1)
            lang_menu.addItem_(li)
        lang_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            current_lang_label, None, ""
        )
        lang_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "text.bubble", "Language"
        )
        if lang_img is not None:
            lang_img.setSize_(NSMakeSize(16, 16))
            lang_item.setImage_(lang_img)
        lang_item.setSubmenu_(lang_menu)
        menu.addItem_(lang_item)
        self.langMenuItem = lang_item

        menu.addItem_(NSMenuItem.separatorItem())

        # --- Version
        ver_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Version 1.0", None, ""
        )
        ver_item.setEnabled_(False)
        menu.addItem_(ver_item)

        # --- Quit
        menu.addItem_(self._menu_item("Quit", "quitApp:", "q"))

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
        b.layer().setBorderWidth_(0.5)
        b.layer().setBorderColor_(
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.16).CGColor()
        )
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
        content.layer().setBorderColor_(
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.14).CGColor()
        )
        panel.setContentView_(content)

        # Vibrant blue tint over the frosted glass (a sublayer, so it doesn't
        # intercept clicks or block window dragging).
        tint = CALayer.layer()
        tint.setFrame_(NSMakeRect(0, 0, PILL_W, PILL_H))
        tint.setBackgroundColor_(accent_blue(0.10).CGColor())
        content.layer().addSublayer_(tint)
        self.pillContent = content
        self.tintLayer = tint

        # Animated gradient shown only while transcribing. The color stops
        # sweep across the pill (locations animation) for a loading shimmer.
        grad = CAGradientLayer.layer()
        grad.setFrame_(NSMakeRect(0, 0, PILL_W, PILL_H))
        grad.setColors_([
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.02, 0.10, 0.48, 0.92).CGColor(),
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.10, 0.42, 0.98, 0.95).CGColor(),
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.45, 0.80, 1.00, 0.95).CGColor(),
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.02, 0.10, 0.48, 0.92).CGColor(),
        ])
        grad.setLocations_([0.0, 0.35, 0.65, 1.0])
        grad.setStartPoint_((0.0, 0.5))
        grad.setEndPoint_((1.0, 0.5))
        grad.setOpacity_(0.0)
        content.layer().addSublayer_(grad)
        self.gradientLayer = grad

        # Translucent backgrounds so the pill glass shows through
        self.cancelButton = self._circle_button(
            NSMakeRect(9, 9, 34, 34), "xmark", "cancelClicked:",
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.10), NSColor.whiteColor(),
        )
        content.addSubview_(self.cancelButton)

        self.doneButton = self._circle_button(
            NSMakeRect(PILL_W - 9 - 34, 9, 34, 34), "checkmark", "doneClicked:",
            accent_blue(0.32), NSColor.whiteColor(),
        )
        content.addSubview_(self.doneButton)

        self.copyButton = self._circle_button(
            NSMakeRect(PILL_W_COMPACT - 9 - 28, 12, 28, 28), "doc.on.doc", "copyAgainClicked:",
            accent_blue(0.9), NSColor.whiteColor(),
        )
        self.copyButton.setHidden_(True)
        content.addSubview_(self.copyButton)

        # Translucent background so the animated gradient shows through
        self.cancelMiniButton = self._circle_button(
            NSMakeRect(8, 12, 22, 22), "xmark", "cancelTranscribeClicked:",
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.18), NSColor.whiteColor(),
        )
        self.cancelMiniButton.setHidden_(True)
        content.addSubview_(self.cancelMiniButton)

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
    def _resize_pill(self, w, h=PILL_H, animate=True):
        scr = NSScreen.mainScreen().frame()
        x = scr.origin.x + (scr.size.width - w) / 2.0
        # Keep the vertical center where the full-height pill sits
        y = scr.origin.y + scr.size.height - 64 - (PILL_H + h) / 2.0
        self.panel.setFrame_display_animate_(NSMakeRect(x, y, w, h), True, animate)
        self.pillContent.setFrame_(NSMakeRect(0, 0, w, h))
        self.pillContent.layer().setCornerRadius_(h / 2.0)
        self.tintLayer.setFrame_(NSMakeRect(0, 0, w, h))
        self.gradientLayer.setFrame_(NSMakeRect(0, 0, w, h))

    @objc.python_method
    def _show_pill(self):
        scr = NSScreen.mainScreen().frame()
        w = self.panel.frame().size.width
        h = self.panel.frame().size.height
        x = scr.origin.x + (scr.size.width - w) / 2.0
        y = scr.origin.y + scr.size.height - 64 - (PILL_H + h) / 2.0
        self.panel.setFrameOrigin_(NSMakePoint(x, y))
        self.panel.orderFrontRegardless()

    @objc.python_method
    def _hide_pill(self):
        self.panel.orderOut_(None)

    @objc.python_method
    def _start_gradient(self):
        self.gradientLayer.setOpacity_(1.0)
        anim = CABasicAnimation.animationWithKeyPath_("locations")
        anim.setFromValue_([-1.0, -0.65, -0.35, 0.0])
        anim.setToValue_([1.0, 1.35, 1.65, 2.0])
        anim.setDuration_(1.8)
        anim.setRepeatCount_(float("inf"))
        self.gradientLayer.addAnimation_forKey_(anim, "shimmer")

    @objc.python_method
    def _stop_gradient(self):
        self.gradientLayer.setOpacity_(0.0)
        self.gradientLayer.removeAllAnimations()

    @objc.python_method
    def _set_pill_state(self, st):
        listening = st == "listening"
        transcribing = st == "transcribing"
        done = st == "done"

        self.waveform.setHidden_(not listening)
        self.cancelButton.setHidden_(not listening)
        self.doneButton.setHidden_(not listening)
        self.spinner.setHidden_(True)
        self.spinner.stopAnimation_(None)
        self.copyButton.setHidden_(not done)
        self.cancelMiniButton.setHidden_(not transcribing)
        if transcribing:
            self._start_gradient()
        else:
            self._stop_gradient()

        label_text = {
            "listening": "Listening",
            "transcribing": "Transcribing…",
            "done": "Copied ✓",
        }.get(st, "")
        self.statusLabel.setStringValue_(label_text)
        if not transcribing:
            self.statusLabel.setFont_(ui_font(14, "medium"))

        if transcribing:
            # Mini pill: cancel X + small label over the animated gradient
            w = PILL_W_MINI
            self.cancelMiniButton.setFrame_(
                NSMakeRect(8, (PILL_H_MINI - 22) / 2.0, 22, 22)
            )
            self.statusLabel.setFont_(ui_font(12, "medium"))
            self.statusLabel.setFrame_(
                NSMakeRect(30, (PILL_H_MINI - 16) / 2.0, w - 30 - 8, 16)
            )
            self.statusLabel.setAlignment_(NSTextAlignmentCenter)
            self._resize_pill(w, PILL_H_MINI)
        elif done:
            # Label centered in the free space left of the copy button
            w = PILL_W_COMPACT
            btn_x = w - 9 - 28
            self.statusLabel.setFrame_(NSMakeRect(0, (PILL_H - 20) / 2.0, btn_x, 20))
            self.statusLabel.setAlignment_(NSTextAlignmentCenter)
            self.copyButton.setFrame_(NSMakeRect(btn_x, (PILL_H - 28) / 2.0, 28, 28))
            self._resize_pill(w)
        else:
            self.statusLabel.setFrame_(NSMakeRect(144, 16, 120, 20))
            self.statusLabel.setAlignment_(NSTextAlignmentLeft)
            self._resize_pill(PILL_W)

    @objc.python_method
    def _set_mic_active(self, active):
        btn = self.statusItem.button()
        if active:
            stop_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "stop.fill", "Stop"
            )
            if stop_img is not None:
                stop_img.setSize_(NSMakeSize(17, 17))
                stop_img.setTemplate_(True)
                btn.setImage_(stop_img)
            btn.setContentTintColor_(NSColor.systemRedColor())
        else:
            mic_img = self._load_svg_icon()
            if mic_img is not None:
                btn.setImage_(mic_img)
            btn.setContentTintColor_(None)

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
        self.copyButton.setHidden_(True)
        self.cancelMiniButton.setHidden_(True)
        self._show_pill()
        self._schedule_hide(1.4)

    @objc.python_method
    def _transcribe_thread(self, audio):
        gen = self._tgen
        try:
            text = self.transcriber.transcribe(
                audio, language=self.language, initial_prompt=self.vocabulary
            )
            AppHelper.callAfter(self._on_transcribed, gen, text or "")
        except Exception as exc:  # noqa: BLE001
            AppHelper.callAfter(self._on_error, gen, str(exc))

    @objc.python_method
    def _on_transcribed(self, gen, text):
        if gen != self._tgen:
            return  # cancelled while transcribing
        text = text.strip()
        if text:
            self.store.add_history(text)
            self._last_text = text
            self._set_pill_state("done")
            if self.auto_copy:
                self._copy_to_clipboard(text)
            else:
                self.statusLabel.setStringValue_("Done")
            self.state = "idle"
            self._schedule_hide(3.5)
        else:
            self._set_pill_state("idle")
            self.statusLabel.setStringValue_("No speech")
            self.state = "idle"
            self._schedule_hide(1.2)

    @objc.python_method
    def _on_error(self, gen, msg):
        if gen != self._tgen:
            return  # cancelled while transcribing
        self._set_pill_state("idle")
        self.statusLabel.setStringValue_("Error")
        self.state = "idle"
        self._schedule_hide(1.6)

    @objc.python_method
    def _schedule_hide(self, delay):
        t = getattr(self, "_hideTimer", None)
        if t is not None:
            t.invalidate()
        self._hideTimer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            delay, self, "autoHide:", None, False
        )

    def autoHide_(self, timer):
        if self.state == "idle":
            self._hide_pill()

    def copyAgainClicked_(self, sender):
        text = getattr(self, "_last_text", "")
        if text:
            self._copy_to_clipboard(text)
            self.statusLabel.setStringValue_("Copied ✓")
        self._schedule_hide(1.5)

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
    @objc.python_method
    def _settings_glass_card(self, parent, x, y, w, h):
        v = NSView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        v.setWantsLayer_(True)
        v.layer().setBackgroundColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.55, 0.55, 0.60, 0.14).CGColor()
        )
        v.layer().setCornerRadius_(10.0)
        v.layer().setBorderWidth_(0.5)
        v.layer().setBorderColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.09).CGColor()
        )
        parent.addSubview_(v)
        return v

    @objc.python_method
    def _settings_header(self, parent, text, x, y, w):
        lbl = NSTextField.labelWithString_(text.upper())
        lbl.setFrame_(NSMakeRect(x, y, w, 13))
        lbl.setFont_(NSFont.systemFontOfSize_(10))
        lbl.setTextColor_(NSColor.secondaryLabelColor())
        parent.addSubview_(lbl)

    @objc.python_method
    def _settings_row_sep(self, parent, x, y, w):
        s = NSView.alloc().initWithFrame_(NSMakeRect(x, y, w, 0.5))
        s.setWantsLayer_(True)
        s.layer().setBackgroundColor_(NSColor.separatorColor().CGColor())
        parent.addSubview_(s)

    @objc.python_method
    def _settings_popup_row(self, parent, card_w, row_y, row_h, label_text, action):
        lbl = NSTextField.labelWithString_(label_text)
        lbl.setFrame_(NSMakeRect(16, row_y + (row_h - 20) // 2, 130, 20))
        lbl.setTextColor_(NSColor.labelColor())
        lbl.setFont_(NSFont.systemFontOfSize_(13))
        parent.addSubview_(lbl)
        px = 160
        pw = card_w - px - 16
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(px, row_y + (row_h - 26) // 2, pw, 26), False
        )
        popup.setTarget_(self)
        popup.setAction_(action)
        parent.addSubview_(popup)
        return popup

    @objc.python_method
    def _settings_text_row(self, parent, card_w, row_y, row_h, label_text, placeholder=""):
        lbl = NSTextField.labelWithString_(label_text)
        lbl.setFrame_(NSMakeRect(16, row_y + (row_h - 20) // 2, 130, 20))
        lbl.setTextColor_(NSColor.labelColor())
        lbl.setFont_(NSFont.systemFontOfSize_(13))
        parent.addSubview_(lbl)
        px = 160
        pw = card_w - px - 16
        field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(px, row_y + (row_h - 24) // 2, pw, 24)
        )
        field.setPlaceholderString_(placeholder)
        field.setBezeled_(True)
        field.setFont_(NSFont.systemFontOfSize_(12))
        parent.addSubview_(field)
        return field

    @objc.python_method
    def _build_settings_config_section(self, cw, H):
        sec = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, H))

        # Top-anchored layout (Cocoa: y=0 at bottom, so we walk a `top` cursor
        # downward from just under the transparent titlebar). Each card's frame
        # y is its bottom edge: top - height.
        PAD = 24
        card_w = cw - PAD * 2
        top = H - 40

        # --- Title + subtitle
        title = NSTextField.labelWithString_("Configuration")
        title.setFrame_(NSMakeRect(PAD, top - 26, card_w, 26))
        title.setFont_(NSFont.boldSystemFontOfSize_(20))
        title.setTextColor_(NSColor.labelColor())
        sec.addSubview_(title)
        top -= 26

        sub = NSTextField.labelWithString_("Model, language and audio input.")
        sub.setFrame_(NSMakeRect(PAD, top - 20, card_w, 16))
        sub.setFont_(NSFont.systemFontOfSize_(12))
        sub.setTextColor_(NSColor.secondaryLabelColor())
        sec.addSubview_(sub)
        top -= 20 + 26

        def group(header_text, card_h):
            nonlocal top
            self._settings_header(sec, header_text, PAD, top - 13, card_w)
            top -= 13 + 8
            card = self._settings_glass_card(sec, PAD, top - card_h, card_w, card_h)
            top -= card_h + 22
            return card

        # --- Transcription (primary settings first)
        trans_card = group("Transcription", 144)
        self.modelPopup = self._settings_popup_row(trans_card, card_w, 96, 48, "Model", "modelChanged:")
        self.modelPopup.addItemsWithTitles_(MODELS)
        self._settings_row_sep(trans_card, 16, 96, card_w - 32)
        self.langPopup = self._settings_popup_row(trans_card, card_w, 48, 48, "Language", "settingsLanguageChanged:")
        self.langPopup.addItemsWithTitles_([lbl for lbl, _ in LANGUAGES])
        self._settings_row_sep(trans_card, 16, 48, card_w - 32)
        self.vocabField = self._settings_text_row(
            trans_card, card_w, 0, 48, "Vocabulary",
            placeholder="Names, jargon to bias toward (optional)",
        )
        self.vocabField.setStringValue_(self.vocabulary or "")
        self.vocabField.setDelegate_(self)

        # --- Audio
        audio_card = group("Audio", 48)
        self.micPopup = self._settings_popup_row(audio_card, card_w, 0, 48, "Microphone", "micChanged:")

        # --- General
        gen_card = group("General", 48)
        self.autoCopyCheck = NSButton.checkboxWithTitle_target_action_(
            "Copy to clipboard automatically", self, "autoCopyToggled:"
        )
        self.autoCopyCheck.setFrame_(NSMakeRect(16, 13, card_w - 32, 22))
        gen_card.addSubview_(self.autoCopyCheck)

        # --- Status line, pinned to the bottom
        self.settingsStatus = NSTextField.labelWithString_("")
        self.settingsStatus.setFrame_(NSMakeRect(PAD, 16, card_w, 16))
        self.settingsStatus.setTextColor_(NSColor.tertiaryLabelColor())
        self.settingsStatus.setFont_(NSFont.systemFontOfSize_(11))
        sec.addSubview_(self.settingsStatus)

        return sec

    @objc.python_method
    def _build_settings_history_section(self, cw, H):
        sec = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, H))

        PAD = 24

        title_lbl = NSTextField.labelWithString_("History")
        title_lbl.setFrame_(NSMakeRect(PAD, H - 66, cw - PAD * 2, 26))
        title_lbl.setFont_(NSFont.boldSystemFontOfSize_(20))
        title_lbl.setTextColor_(NSColor.labelColor())
        sec.addSubview_(title_lbl)

        sub_lbl = NSTextField.labelWithString_("Your last 5 transcriptions. Click any to copy.")
        sub_lbl.setFrame_(NSMakeRect(PAD, H - 86, cw - PAD * 2, 16))
        sub_lbl.setFont_(NSFont.systemFontOfSize_(12))
        sub_lbl.setTextColor_(NSColor.secondaryLabelColor())
        sec.addSubview_(sub_lbl)

        clear_btn = NSButton.alloc().initWithFrame_(NSMakeRect(PAD, 16, 120, 28))
        clear_btn.setTitle_("Clear History")
        clear_btn.setBezelStyle_(1)  # NSRoundedBezelStyle
        clear_btn.setTarget_(self)
        clear_btn.setAction_("clearHistory:")
        sec.addSubview_(clear_btn)
        self._clearHistBtn = clear_btn

        # Cards container, between the subtitle and the clear button
        self._hist_container = NSView.alloc().initWithFrame_(
            NSMakeRect(PAD, 56, cw - PAD * 2, H - 152)
        )
        sec.addSubview_(self._hist_container)

        return sec

    @objc.python_method
    def _build_settings_about_section(self, cw, H):
        sec = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, H))

        # Hero block (icon + name + version) and the info card are centered as
        # one group so the section doesn't leave an empty bottom half. Each
        # element's y is expressed as an offset from the vertical center so
        # the whole group re-centers correctly if H ever changes.
        mid = H // 2

        # Icon
        icon_img = self._load_svg_icon(52)
        if icon_img:
            icon_btn = NSButton.alloc().initWithFrame_(NSMakeRect(cw // 2 - 26, mid + 88, 52, 52))
            icon_btn.setBordered_(False)
            icon_btn.setImage_(icon_img)
            icon_btn.setImagePosition_(NSImageOnly)
            icon_btn.setEnabled_(False)
            sec.addSubview_(icon_btn)

        name_lbl = NSTextField.labelWithString_("Lyrebird")
        name_lbl.setFrame_(NSMakeRect(0, mid + 48, cw, 26))
        name_lbl.setAlignment_(NSTextAlignmentCenter)
        name_lbl.setFont_(NSFont.boldSystemFontOfSize_(20))
        name_lbl.setTextColor_(NSColor.labelColor())
        sec.addSubview_(name_lbl)

        ver_lbl = NSTextField.labelWithString_("Version 1.0  ·  100% local speech-to-text")
        ver_lbl.setFrame_(NSMakeRect(0, mid + 28, cw, 18))
        ver_lbl.setAlignment_(NSTextAlignmentCenter)
        ver_lbl.setFont_(NSFont.systemFontOfSize_(12))
        ver_lbl.setTextColor_(NSColor.secondaryLabelColor())
        sec.addSubview_(ver_lbl)

        # Info card
        info_card = self._settings_glass_card(sec, 24, mid - 112, cw - 48, 100)
        for i, (label, value) in enumerate([
            ("Hotkey", "⇧⌘L  start / stop recording"),
            ("Right-click icon", "Language, history, settings, quit"),
            ("Config", "~/Library/Application Support/Lyrebird"),
        ]):
            row_y = 100 - 26 - i * 26
            lbl = NSTextField.labelWithString_(label)
            lbl.setFrame_(NSMakeRect(16, row_y, 130, 18))
            lbl.setFont_(NSFont.systemFontOfSize_(11))
            lbl.setTextColor_(NSColor.secondaryLabelColor())
            info_card.addSubview_(lbl)
            val = NSTextField.labelWithString_(value)
            val.setFrame_(NSMakeRect(150, row_y, cw - 48 - 150 - 16, 18))
            val.setFont_(NSFont.systemFontOfSize_(11))
            val.setTextColor_(NSColor.labelColor())
            info_card.addSubview_(val)

        lic_lbl = NSTextField.labelWithString_(
            "MIT License © 2026 Painted Bird  ·  Whisper (MIT)  ·  Arimo font (OFL 1.1)"
        )
        lic_lbl.setFrame_(NSMakeRect(0, 20, cw, 16))
        lic_lbl.setAlignment_(NSTextAlignmentCenter)
        lic_lbl.setFont_(NSFont.systemFontOfSize_(10))
        lic_lbl.setTextColor_(NSColor.tertiaryLabelColor())
        sec.addSubview_(lic_lbl)

        return sec

    def _build_settings(self):
        W, H = 640, 508
        SIDEBAR = 170
        cw = W - SIDEBAR - 1

        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
        )
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False
        )
        win.setTitle_("Lyrebird")
        win.setReleasedWhenClosed_(False)
        win.setTitlebarAppearsTransparent_(True)
        win.center()
        win.setDelegate_(self)

        bg = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        bg.setMaterial_(NSVisualEffectMaterialWindowBackground)
        bg.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        bg.setState_(NSVisualEffectStateActive)
        win.setContentView_(bg)

        # ---- Sidebar
        sidebar = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, SIDEBAR, H))
        sidebar.setWantsLayer_(True)
        sidebar.layer().setBackgroundColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.20).CGColor()
        )
        bg.addSubview_(sidebar)

        sep_v = NSView.alloc().initWithFrame_(NSMakeRect(SIDEBAR, 0, 1, H))
        sep_v.setWantsLayer_(True)
        sep_v.layer().setBackgroundColor_(NSColor.separatorColor().CGColor())
        bg.addSubview_(sep_v)

        app_lbl = NSTextField.labelWithString_("Lyrebird")
        app_lbl.setFrame_(NSMakeRect(14, H - 48, SIDEBAR - 20, 24))
        app_lbl.setFont_(NSFont.boldSystemFontOfSize_(14))
        app_lbl.setTextColor_(NSColor.labelColor())
        sidebar.addSubview_(app_lbl)

        # Sidebar nav items
        self._settings_nav_btns = {}
        nav_items = [
            ("config",   "gearshape.fill",          "Configuration"),
            ("history",  "clock.arrow.circlepath",  "History"),
            ("about",    "info.circle.fill",         "About"),
        ]
        for i, (sec_id, symbol, title) in enumerate(nav_items):
            item_y = H - 88 - i * 44
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(8, item_y, SIDEBAR - 16, 36))
            btn.setBordered_(False)
            btn.setButtonType_(0)
            btn.setWantsLayer_(True)
            btn.layer().setCornerRadius_(8.0)
            sym_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol, title)
            if sym_img:
                sym_img.setSize_(NSMakeSize(14, 14))
                btn.setImage_(sym_img)
            btn.setImagePosition_(NSImageLeft)
            btn.setTitle_("   " + title)
            btn.setFont_(NSFont.systemFontOfSize_(12))
            btn.setTarget_(self)
            btn.setAction_("settingsSidebarClicked:")
            btn.setRepresentedObject_(sec_id)
            sidebar.addSubview_(btn)
            self._settings_nav_btns[sec_id] = btn

        # ---- Content container
        cc = NSView.alloc().initWithFrame_(NSMakeRect(SIDEBAR + 1, 0, cw, H))
        bg.addSubview_(cc)

        # Build section views
        self._settings_section_views = {}
        for sec_id, builder in [
            ("config",  lambda: self._build_settings_config_section(cw, H)),
            ("history", lambda: self._build_settings_history_section(cw, H)),
            ("about",   lambda: self._build_settings_about_section(cw, H)),
        ]:
            v = builder()
            cc.addSubview_(v)
            self._settings_section_views[sec_id] = v

        # Show config by default
        self._settings_active_section = "config"
        for sec_id, v in self._settings_section_views.items():
            v.setHidden_(sec_id != "config")
        self._settings_update_nav("config")

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
        if getattr(self, "vocabField", None) is not None:
            self.vocabField.setStringValue_(self.vocabulary or "")
        self._set_settings_status(
            "Model ready: %s" % self.transcriber.model_name
            if self.modelReady
            else "Loading model…"
        )

    @objc.python_method
    def _set_settings_status(self, text):
        if self.settingsStatus is not None:
            self.settingsStatus.setStringValue_(text)

    def openSettings_(self, sender):
        try:
            if self.settingsWindow is None:
                print("[settings] building...", flush=True)
                self._build_settings()
                print("[settings] built ok", flush=True)
            self._sync_settings()
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            self.settingsWindow.makeKeyAndOrderFront_(None)
        except Exception:
            import traceback
            print("[settings] CRASH:\n" + traceback.format_exc(), flush=True)

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

    def setDeviceFromMenu_(self, sender):
        name_str = sender.representedObject()
        name = None if name_str == DEFAULT_MIC else name_str
        self.recorder.set_device(name)
        self.store.set("device", name)
        # update checkmark and label
        if hasattr(self, "micMenuItem"):
            self.micMenuItem.setTitle_(name_str)
            for i in range(self.micMenuItem.submenu().numberOfItems()):
                mi = self.micMenuItem.submenu().itemAtIndex_(i)
                mi.setState_(1 if mi.representedObject() == name_str else 0)

    def autoCopyToggled_(self, sender):
        self.auto_copy = bool(sender.state())
        self.store.set("auto_copy", self.auto_copy)

    def controlTextDidEndEditing_(self, notification):
        field = notification.object()
        if field is getattr(self, "vocabField", None):
            self.vocabulary = field.stringValue()
            self.store.set("vocabulary", self.vocabulary)

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

    def cancelTranscribeClicked_(self, sender):
        if self.state == "transcribing":
            self._tgen += 1
        self.state = "idle"
        self._stop_gradient()
        self._hide_pill()

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
        if hasattr(self, "langMenuItem"):
            self.langMenuItem.setTitle_(label)
            for i in range(self.langMenuItem.submenu().numberOfItems()):
                li = self.langMenuItem.submenu().itemAtIndex_(i)
                li.setState_(1 if li.representedObject() == label else 0)

    def copyHistory_(self, sender):
        text = sender.representedObject()
        if not text:
            return
        self._copy_to_clipboard(text)
        self._last_text = text
        self.state = "idle"
        self._set_pill_state("done")
        self._show_pill()
        self._schedule_hide(3.5)

    def clearHistory_(self, sender):
        self.store.clear_history()
        if hasattr(self, "_hist_container") and self._hist_container is not None:
            self._refresh_settings_history()

    def settingsSidebarClicked_(self, sender):
        sec_id = sender.representedObject()
        if sec_id == self._settings_active_section:
            return
        self._settings_section_views[self._settings_active_section].setHidden_(True)
        self._settings_active_section = sec_id
        self._settings_section_views[sec_id].setHidden_(False)
        if sec_id == "history":
            self._refresh_settings_history()
        self._settings_update_nav(sec_id)

    @objc.python_method
    def _settings_update_nav(self, active_id):
        for sec_id, btn in self._settings_nav_btns.items():
            if sec_id == active_id:
                btn.layer().setBackgroundColor_(accent_blue(0.20).CGColor())
                btn.setContentTintColor_(accent_blue(1.0))
            else:
                btn.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
                btn.setContentTintColor_(NSColor.secondaryLabelColor())

    @objc.python_method
    def _refresh_settings_history(self):
        if not hasattr(self, "_hist_container") or self._hist_container is None:
            return
        for sv in list(self._hist_container.subviews()):
            sv.removeFromSuperview()

        history = self.store.history()
        container_w = self._hist_container.frame().size.width
        container_h = self._hist_container.frame().size.height
        card_h, gap = 68, 10

        if getattr(self, "_clearHistBtn", None) is not None:
            self._clearHistBtn.setEnabled_(bool(history))

        if not history:
            cy = container_h // 2
            sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "clock.arrow.circlepath", "History"
            )
            if sym is not None:
                sym.setSize_(NSMakeSize(34, 34))
                ib = NSButton.alloc().initWithFrame_(
                    NSMakeRect(container_w // 2 - 17, cy + 8, 34, 34)
                )
                ib.setBordered_(False)
                ib.setImage_(sym)
                ib.setImagePosition_(NSImageOnly)
                ib.setEnabled_(False)
                ib.setContentTintColor_(NSColor.tertiaryLabelColor())
                self._hist_container.addSubview_(ib)

            empty = NSTextField.labelWithString_("No transcriptions yet")
            empty.setFrame_(NSMakeRect(0, cy - 18, container_w, 20))
            empty.setAlignment_(NSTextAlignmentCenter)
            empty.setTextColor_(NSColor.secondaryLabelColor())
            empty.setFont_(NSFont.systemFontOfSize_(13))
            self._hist_container.addSubview_(empty)

            hint = NSTextField.labelWithString_("Press ⇧⌘L anywhere to start dictating.")
            hint.setFrame_(NSMakeRect(0, cy - 38, container_w, 16))
            hint.setAlignment_(NSTextAlignmentCenter)
            hint.setTextColor_(NSColor.tertiaryLabelColor())
            hint.setFont_(NSFont.systemFontOfSize_(11))
            self._hist_container.addSubview_(hint)
            return

        for i, entry in enumerate(history):
            y = container_h - (i + 1) * (card_h + gap) + gap // 2
            text = entry.get("text", "")

            # Glass card
            card = self._settings_glass_card(
                self._hist_container, 0, y, container_w, card_h
            )

            # Text preview (top line)
            preview = " ".join(text.split())
            short = preview[:100] + ("…" if len(preview) > 100 else "")
            txt = NSTextField.labelWithString_(short)
            txt.setFrame_(NSMakeRect(14, card_h - 34, container_w - 60, 20))
            txt.setFont_(NSFont.systemFontOfSize_(12))
            txt.setTextColor_(NSColor.labelColor())
            card.addSubview_(txt)

            # Word count line
            wc = NSTextField.labelWithString_("%d words" % len(preview.split()))
            wc.setFrame_(NSMakeRect(14, 12, 120, 15))
            wc.setFont_(NSFont.systemFontOfSize_(10))
            wc.setTextColor_(NSColor.secondaryLabelColor())
            card.addSubview_(wc)

            # Copy icon button
            copy_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "doc.on.doc", "Copy"
            )
            copy_btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(container_w - 44, (card_h - 22) // 2, 22, 22)
            )
            copy_btn.setBordered_(False)
            if copy_img:
                copy_img.setSize_(NSMakeSize(16, 16))
                copy_btn.setImage_(copy_img)
                copy_btn.setImagePosition_(NSImageOnly)
            copy_btn.setContentTintColor_(NSColor.secondaryLabelColor())
            copy_btn.setTarget_(self)
            copy_btn.setAction_("historyCardClicked:")
            copy_btn.setRepresentedObject_(text)
            card.addSubview_(copy_btn)

            # Transparent click overlay covering the card
            overlay = NSButton.alloc().initWithFrame_(
                NSMakeRect(0, 0, container_w - 50, card_h)
            )
            overlay.setBordered_(False)
            overlay.setTitle_("")
            overlay.setTarget_(self)
            overlay.setAction_("historyCardClicked:")
            overlay.setRepresentedObject_(text)
            card.addSubview_(overlay)

    def historyCardClicked_(self, sender):
        text = sender.representedObject()
        if text:
            self._copy_to_clipboard(text)
            self._flash("Copied ✓")

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
