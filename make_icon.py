#!/usr/bin/env python3
"""Generate AppIcon.icns for the .app bundle.

Run once:  .venv/bin/python make_icon.py
"""
import os
import shutil
import subprocess
import tempfile

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyProhibited,
    NSBitmapImageRep,
    NSColor,
    NSCompositingOperationSourceAtop,
    NSCompositingOperationSourceOver,
    NSImage,
    NSImageSymbolConfiguration,
    NSMakeRect,
    NSPNGFileType,
    NSRectFill,
    NSRectFillUsingOperation,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def render_png(pixel_size: int) -> bytes:
    img = NSImage.alloc().initWithSize_((pixel_size, pixel_size))
    img.lockFocus()

    NSColor.clearColor().set()
    NSRectFill(NSMakeRect(0, 0, pixel_size, pixel_size))

    sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
        "mic.circle.fill", "Lyrebird"
    )
    if sym is not None:
        cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(
            float(pixel_size), 6, 3
        )
        sym = sym.imageWithSymbolConfiguration_(cfg)
        sym_size = sym.size()
        dest = NSMakeRect(
            (pixel_size - sym_size.width) / 2,
            (pixel_size - sym_size.height) / 2,
            sym_size.width,
            sym_size.height,
        )
        sym.drawInRect_fromRect_operation_fraction_(
            dest, NSMakeRect(0, 0, 0, 0), NSCompositingOperationSourceOver, 1.0
        )
        NSColor.colorWithSRGBRed_green_blue_alpha_(0.20, 0.55, 1.0, 1.0).set()
        NSRectFillUsingOperation(
            NSMakeRect(0, 0, pixel_size, pixel_size), NSCompositingOperationSourceAtop
        )

    img.unlockFocus()

    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    png_data = rep.representationUsingType_properties_(NSPNGFileType, None)
    return bytes(png_data)


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyProhibited)

    # (pixel_size, iconset_filename)
    entries = [
        (16,   "icon_16x16.png"),
        (32,   "icon_16x16@2x.png"),
        (32,   "icon_32x32.png"),
        (64,   "icon_32x32@2x.png"),
        (128,  "icon_128x128.png"),
        (256,  "icon_128x128@2x.png"),
        (256,  "icon_256x256.png"),
        (512,  "icon_256x256@2x.png"),
        (512,  "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]

    iconset_dir = tempfile.mkdtemp(suffix=".iconset")
    cache: dict = {}

    try:
        for size, name in entries:
            if size not in cache:
                cache[size] = render_png(size)
            with open(os.path.join(iconset_dir, name), "wb") as f:
                f.write(cache[size])

        out = os.path.join(HERE, "AppIcon.icns")
        subprocess.run(
            ["iconutil", "-c", "icns", iconset_dir, "-o", out], check=True
        )
        print("Icon saved:", out)
    finally:
        shutil.rmtree(iconset_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
