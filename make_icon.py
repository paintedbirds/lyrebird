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
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSCompositingOperationSourceOver,
    NSGradient,
    NSGraphicsContext,
    NSImage,
    NSMakeRect,
    NSMakeSize,
    NSPNGFileType,
    NSRectFill,
    NSShadow,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def render_png(pixel_size: int) -> bytes:
    img = NSImage.alloc().initWithSize_((pixel_size, pixel_size))
    img.lockFocus()
    ctx = NSGraphicsContext.currentContext()

    # Transparent canvas (rounded corners show through).
    NSColor.clearColor().set()
    NSRectFill(NSMakeRect(0, 0, pixel_size, pixel_size))

    # --- Blue-gradient squircle background (macOS app-icon proportions).
    margin = pixel_size * 0.085
    side = pixel_size - 2 * margin
    radius = side * 0.2237
    rect = NSMakeRect(margin, margin, side, side)
    bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, radius, radius)

    top = NSColor.colorWithSRGBRed_green_blue_alpha_(0.42, 0.66, 1.00, 1.0)
    bottom = NSColor.colorWithSRGBRed_green_blue_alpha_(0.09, 0.26, 0.78, 1.0)
    grad = NSGradient.alloc().initWithStartingColor_endingColor_(top, bottom)
    grad.drawInBezierPath_angle_(bg, -90.0)  # top -> bottom

    # --- White bird logo with a soft drop shadow, centered.
    ctx.saveGraphicsState()
    shadow = NSShadow.alloc().init()
    shadow.setShadowColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(0, 0, 0, 0.32))
    shadow.setShadowOffset_(NSMakeSize(0, -pixel_size * 0.012))
    shadow.setShadowBlurRadius_(pixel_size * 0.03)
    shadow.set()

    bird = NSImage.alloc().initWithContentsOfFile_(os.path.join(HERE, "icon-app.svg"))
    if bird is not None:
        nat = bird.size()
        target_h = side * 0.66
        scale = target_h / nat.height if nat.height else 1.0
        target_w = nat.width * scale
        dest = NSMakeRect(
            margin + (side - target_w) / 2,
            margin + (side - target_h) / 2,
            target_w,
            target_h,
        )
        bird.drawInRect_fromRect_operation_fraction_(
            dest, NSMakeRect(0, 0, 0, 0), NSCompositingOperationSourceOver, 1.0
        )
    ctx.restoreGraphicsState()

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
