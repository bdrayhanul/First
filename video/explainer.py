#!/usr/bin/env python3
"""
Build a narrated explainer with real motion design and sound.

  python3 explainer.py            -> out/explainer.avi  (MJPEG + 48 kHz PCM)
                                     out/explainer.wav  (the mix on its own)
                                     out/contact.png    (frame grid)

Video is drawn with Pillow at 2x and downsampled (clean edges), animated with
eased keyframes, and encoded as MJPEG inside an AVI that carries the audio in
a second stream. The music bed, whooshes, blips and riser are synthesised in
audio_synth.py; only the Bangla voice-over is fetched (and cached) from TTS.
"""

import io
import math
import os
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

import audio_synth as A
from avilib import write_avi_mjpeg

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
VOICE_DIR = os.path.join(HERE, "assets", "voice")

VW, VH, SS = 640, 360, 3         # design units; drawn at 3x for real AA
OW, OH = 1280, 720                # output resolution
FPS = 24
TRANS = 0.36                      # transition length (s)

INK = (11, 16, 32)
INK2 = (20, 28, 54)
AMBER = (255, 180, 84)
CYAN = (79, 209, 197)
PINK = (244, 114, 182)
WHITE = (244, 247, 255)
DIM = (150, 165, 200)
RED = (255, 99, 110)

# what ends up on screen: the file name and codec actually written
CODEC_LABEL = "H.264 720P"
FILE_LABEL = "EXPLAINER.MP4  ·  1280x720  ·  H.264  ·  AAC"

BANGLA_B = "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf"
BANGLA_R = "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf"
SANS_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SANS_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONO_B = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

_FONTS = {}


def font(path, size):
    key = (path, size)
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(path, int(size * SS))
    return _FONTS[key]


# ---------------------------------------------------------------- easing ----

def clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def seg(t, a, b):
    """normalised progress of t through the window [a, b]"""
    if b <= a:
        return 1.0 if t >= b else 0.0
    return clamp01((t - a) / (b - a))


def ease_out(t):
    return 1.0 - (1.0 - t) ** 3


def ease_in_out(t):
    return 3 * t * t - 2 * t * t * t


def ease_out_back(t, s=1.9):
    t -= 1.0
    return 1.0 + t * t * ((s + 1) * t + s)


def ease_out_expo(t):
    return 1.0 if t >= 1.0 else 1.0 - 2.0 ** (-10.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def mixc(c1, c2, t):
    t = clamp01(t)
    return tuple(int(round(lerp(c1[i], c2[i], t))) for i in range(3))


# ----------------------------------------------------------- the drawing ----

_GLOW = None
_VIGNETTE = None
_GRAIN = None


def glow_sprite():
    global _GLOW
    if _GLOW is None:
        yy, xx = np.mgrid[0:128, 0:128]
        r = np.sqrt((xx - 63.5) ** 2 + (yy - 63.5) ** 2) / 63.5
        _GLOW = Image.fromarray((np.clip(1 - r, 0, 1) ** 2.0 * 255).astype(np.uint8), "L")
    return _GLOW


def vignette_mask():
    global _VIGNETTE
    if _VIGNETTE is None:
        yy, xx = np.mgrid[0:OH, 0:OW]
        r = np.sqrt(((xx - OW / 2) / (OW / 2)) ** 2 +
                    ((yy - OH / 2) / (OH / 2)) ** 2) / 1.414
        _VIGNETTE = Image.fromarray((np.clip(r ** 2.1 * 1.3, 0, 1) * 255).astype(np.uint8), "L")
    return _VIGNETTE


def grain_tile(seed=0):
    global _GRAIN
    if _GRAIN is None:
        rng = np.random.default_rng(seed)
        _GRAIN = [Image.fromarray(rng.integers(100, 156, (OH, OW), dtype=np.uint8), "L")
                  for _ in range(4)]
    return _GRAIN


class Frame:
    """drawing surface in 640x360 design units, rendered SS times larger"""

    def __init__(self, top=INK, bottom=INK2, angle=1.15):
        self.img = Image.new("RGB", (VW * SS, VH * SS), INK)
        small = Image.new("RGB", (8, 96))
        ds = ImageDraw.Draw(small)
        for y in range(96):
            ds.line([(0, y), (8, y)], fill=mixc(top, bottom, (y / 95) ** angle))
        self.img.paste(small.resize((VW * SS, VH * SS), Image.BILINEAR), (0, 0))
        self.d = ImageDraw.Draw(self.img, "RGBA")

    # -- primitives (design units in, pixels out) --
    def rect(self, x, y, w, h, fill, r=0, outline=None, ow=1):
        box = [x * SS, y * SS, (x + w) * SS, (y + h) * SS]
        if r:
            self.d.rounded_rectangle(box, radius=r * SS, fill=fill,
                                     outline=outline, width=max(1, int(ow * SS)))
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=max(1, int(ow * SS)))

    def circle(self, cx, cy, r, fill, outline=None, ow=1):
        self.d.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS],
                       fill=fill, outline=outline, width=max(1, int(ow * SS)))

    def ring(self, cx, cy, r, color, ow=2):
        self.d.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS],
                       outline=color, width=max(1, int(ow * SS)))

    def poly(self, pts, fill, outline=None, ow=1):
        p = [(x * SS, y * SS) for x, y in pts]
        self.d.polygon(p, fill=fill, outline=outline, width=max(1, int(ow * SS)))

    def line(self, pts, color, w=1.5):
        self.d.line([(x * SS, y * SS) for x, y in pts], fill=color,
                    width=max(1, int(w * SS)), joint="curve")

    def text(self, x, y, s, f, color, anchor="la"):
        """alpha-aware text: PIL's text() ignores the fill's alpha, so faded
        text is drawn into a small RGBA tile and composited instead"""
        if not s:
            return
        a = color[3] if len(color) == 4 else 255
        if a <= 0:
            return
        px, py = x * SS, y * SS
        if a >= 255:
            self.d.text((px, py), s, font=f, fill=color[:3], anchor=anchor)
            return
        bbox = self.d.textbbox((px, py), s, font=f, anchor=anchor)
        pad = 3
        w, h = int(bbox[2] - bbox[0]) + 2 * pad, int(bbox[3] - bbox[1]) + 2 * pad
        if w <= 0 or h <= 0:
            return
        tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((px - bbox[0] + pad, py - bbox[1] + pad), s,
                                  font=f, fill=tuple(color[:3]) + (255,), anchor=anchor)
        tile.putalpha(tile.getchannel("A").point(lambda v: v * a // 255))
        self.img.paste(tile, (int(bbox[0]) - pad, int(bbox[1]) - pad), tile)

    def spaced(self, x, y, s, f, color, tracking=1.6, anchor="l"):
        """letter-spaced mono label; returns its width in design units"""
        widths = [self.d.textlength(ch, font=f) / SS for ch in s]
        total = sum(widths) + tracking * max(0, len(s) - 1)
        cx = x - total if anchor == "r" else (x - total / 2 if anchor == "m" else x)
        for ch, w in zip(s, widths):
            self.text(cx, y, ch, f, color, anchor="la")
            cx += w + tracking
        return total

    def twidth(self, s, f):
        return self.d.textlength(s, font=f) / SS

    def glow(self, cx, cy, radius, color, alpha=0.55):
        size = max(4, int(radius * 2 * SS))
        mask = glow_sprite().resize((size, size), Image.BILINEAR)
        if alpha < 1:
            mask = mask.point(lambda v, a=alpha: int(v * a))
        self.paste_solid(color, (int(cx * SS - size / 2), int(cy * SS - size / 2)), mask)

    def paste_solid(self, color, xy, mask):
        self.img.paste(Image.new("RGB", mask.size, color), xy, mask)

    def finish(self):
        """vignette at output resolution; the 2x canvas *is* the 720p frame"""
        out = self.img if self.img.size == (OW, OH) else self.img.resize((OW, OH), Image.LANCZOS)
        return Image.composite(Image.new("RGB", (OW, OH), (0, 0, 0)), out, vignette_mask())


def rgba(rgb, a):
    return (rgb[0], rgb[1], rgb[2], int(round(255 * clamp01(a))))


def chrome(f, gp, label, t):
    """persistent overlay: thin progress line + corner labels"""
    f.rect(0, VH - 3, VW, 3, (255, 255, 255, 14))
    f.rect(0, VH - 3, VW * gp, 3, rgba(AMBER, 0.95))
    f.rect(max(0, VW * gp - 26), VH - 3, 26, 3, rgba(AMBER, 0.25))
    f.spaced(30, VH - 27, label, font(MONO, 9), rgba(DIM, 0.72))
    f.spaced(VW - 30, VH - 27, "EXPLAINER", font(MONO, 9), rgba(DIM, 0.5), anchor="r")


def film_edges(f, t, alpha=0.07):
    off = (t * 26.0) % 34.0
    for k in range(int(VW / 34) + 2):
        x = k * 34 - off
        f.rect(x, 7, 17, 7, rgba(WHITE, alpha), r=2)
        f.rect(x, VH - 14, 17, 7, rgba(WHITE, alpha), r=2)


# ------------------------------------------------------------- scene 1 ------

def scene_intro(t, dur, ctx):
    f = Frame((9, 13, 30), (26, 34, 78))
    f.glow(190 + 34 * math.sin(t * 0.8), 96, 250, (58, 78, 190), 0.50)
    f.glow(478 - 46 * math.sin(t * 0.62), 268, 210, (18, 96, 104), 0.45)
    film_edges(f, t)

    kick_p = ease_out(seg(t, 0.12, 0.62))
    f.spaced(VW / 2, 78, "MOTION  ·  VOICE  ·  SOUND", font(MONO, 9),
             rgba(CYAN, 0.9 * kick_p), tracking=2.4, anchor="m")

    words = ("কোড", "দিয়েই", "ভিডিও")
    fs = font(BANGLA_B, 46)
    widths = [f.twidth(w, fs) for w in words]
    gap = 15.0
    x = (VW - (sum(widths) + gap * (len(words) - 1))) / 2
    for i, (w, wd) in enumerate(zip(words, widths)):
        p = ease_out(seg(t, 0.34 + 0.15 * i, 0.96 + 0.15 * i))
        if p > 0:
            f.text(x, 128 + 30 * (1 - p), w, fs, rgba(WHITE, p), anchor="ls")
        x += wd + gap

    # underline wipe
    up = ease_out(seg(t, 0.95, 1.55))
    if up > 0:
        uw = 210 * up
        f.rect(VW / 2 - uw / 2, 150, uw, 3, rgba(AMBER, 0.95), r=1.5)
        f.glow(VW / 2, 151, 90, (255, 170, 70), 0.28 * up)

    sub_p = ease_out(seg(t, 1.05, 1.6))
    f.text(VW / 2, 183, "শব্দ, ছবি আর অ্যানিমেশন — সব কোড দিয়ে",
           font(BANGLA_R, 17), rgba(DIM, sub_p), anchor="ms")

    chips = (("H.264 720P" if CODEC_LABEL.startswith("H.264") else "MJPEG 720P", AMBER),
             ("48 kHz AUDIO", CYAN), ("BN VOICE-OVER", PINK))
    cf = font(MONO, 9)
    cw = [f.twidth(s, cf) + 24 for s, _ in chips]
    cx = (VW - (sum(cw) + 12 * (len(chips) - 1))) / 2
    for i, ((label, col), width) in enumerate(zip(chips, cw)):
        p = ease_out_back(seg(t, 1.5 + 0.22 * i, 2.0 + 0.22 * i))
        if p > 0:
            h = 24 * p
            y = 226 - 2 * (1 - p)
            f.rect(cx, y, width, h, rgba(mixc(INK2, col, 0.22), 0.9), r=12)
            f.rect(cx, y, width, h, None, r=12, outline=rgba(col, 0.55), ow=1)
            f.spaced(cx + width / 2, y + h / 2 - 4, label, cf,
                     rgba(WHITE, 0.85 * p), tracking=1.6, anchor="m")
        cx += width + 12

    chrome(f, ctx["gp"], "01 / INTRO", t)
    return f


# ------------------------------------------------------------- scene 2 ------

def icon_film(f, x, y, col):
    f.rect(x, y, 34, 26, rgba(col, 0.85), r=3)
    for k in range(3):
        f.rect(x + 4 + k * 11, y + 3, 4, 4, rgba(INK, 0.85), r=1)
        f.rect(x + 4 + k * 11, y + 19, 4, 4, rgba(INK, 0.85), r=1)


def icon_codec(f, x, y, col):
    f.rect(x + 4, y + 4, 26, 18, None, r=2, outline=rgba(col, 0.85), ow=2)
    for k in range(3):
        f.rect(x + 9 + k * 7, y + 9, 4, 8, rgba(col, 0.75), r=1)
        f.rect(x + 9 + k * 7, y, 2, 4, rgba(col, 0.5))
        f.rect(x + 9 + k * 7, y + 22, 2, 4, rgba(col, 0.5))


def icon_wave(f, x, y, col):
    for k, h in enumerate((8, 16, 24, 14, 20, 10)):
        f.rect(x + 2 + k * 5, y + 13 - h / 2, 3, h, rgba(col, 0.8), r=1.5)


def slash(f, x, y, s=34):
    f.line([(x + 2, y + s), (x + s, y + 2)], rgba(RED, 0.9), 2.5)


def scene_problem(t, dur, ctx):
    f = Frame((20, 12, 26), (44, 20, 34))
    f.glow(520 - 30 * math.sin(t * 0.5), 44, 230, (128, 28, 52), 0.50)
    f.glow(60, 330, 200, (60, 18, 40), 0.45)

    hp = ease_out(seg(t, 0.08, 0.52))
    f.text(40 + 20 * (1 - hp), 56, "সমস্যা", font(BANGLA_B, 27),
           rgba(WHITE, hp), anchor="ls")
    f.spaced(42, 64, "WHAT IS MISSING", font(MONO, 9), rgba(RED, 0.85 * hp), tracking=2.2)

    cards = (("ffmpeg", "কোনো এনকোডার নেই", icon_film),
             ("mp4 · mp3", "কোনো ডিকোডার নেই", icon_codec),
             ("samples", "সাউন্ড লাইব্রেরি নেই", icon_wave))
    cw, ch, gap = 182, 128, 18
    x0 = (VW - (cw * 3 + gap * 2)) / 2
    for i, (title, bn, icon) in enumerate(cards):
        p = ease_out(seg(t, 0.45 + 0.24 * i, 1.05 + 0.24 * i))
        if p <= 0:
            continue
        float_y = 3.0 * math.sin(t * 1.5 + i * 1.1) * p
        x = x0 + i * (cw + gap)
        y = 108 + 34 * (1 - p) + float_y
        f.glow(x + cw / 2, y + ch, 96, (90, 20, 45), 0.35 * p)
        f.rect(x, y, cw, ch, rgba((28, 16, 30), 0.92 * p), r=10)
        f.rect(x, y, cw, ch, None, r=10, outline=rgba(RED, 0.35 * p), ow=1.2)
        icon(f, x + 18, y + 16, WHITE, )
        slash(f, x + 16, y + 14, 38)
        f.text(x + 18, y + 74, title, font(MONO_B, 13), rgba(WHITE, 0.95 * p))
        f.text(x + 18, y + 96, bn, font(BANGLA_R, 13), rgba(DIM, 0.92 * p))

    cap = ease_out(seg(t, 1.55, 2.15))
    f.text(VW / 2, 274, "তাই সব নিজে লিখতে হবে", font(BANGLA_B, 19),
           rgba(AMBER, cap), anchor="ms")

    chrome(f, ctx["gp"], "02 / PROBLEM", t)
    return f

# ------------------------------------------------------------- scene 3 ------

def dash_line(f, x1, y, x2, color, dash=7.0, offset=0.0, w=1.6):
    x = x1 - (offset % (dash * 2.0))
    while x < x2:
        a, b = max(x, x1), min(x + dash, x2)
        if b > a:
            f.rect(a, y - w / 2, b - a, w, color, r=w / 2)
        x += dash * 2.0


def scene_solution(t, dur, ctx):
    f = Frame((6, 20, 24), (12, 48, 48))
    f.glow(120 + 40 * math.sin(t * 0.5), 300, 240, (16, 110, 110), 0.45)
    f.glow(540, 60, 200, (14, 90, 120), 0.40)

    hp = ease_out(seg(t, 0.08, 0.55))
    f.text(40 + 20 * (1 - hp), 56, "সমাধান", font(BANGLA_B, 27), rgba(WHITE, hp), anchor="ls")
    f.spaced(42, 64, "WRITE IT YOURSELF", font(MONO, 9), rgba(CYAN, 0.9 * hp), tracking=2.2)

    nodes = (("IMAGEDRAW", "ছবি আঁকা", AMBER),
             ("JPEG ENCODE", "ফ্রেম লেখা", CYAN),
             ("RIFF AVI", "ফাইল বাঁধা", PINK))
    nw, nh, ny = 152, 92, 122
    nx = (44, 244, 444)

    # connectors first, so the nodes sit on top
    for i in range(2):
        x1, x2 = nx[i] + nw + 6, nx[i + 1] - 6
        y = ny + nh / 2
        cp = ease_out(seg(t, 0.6 + 0.3 * i, 1.1 + 0.3 * i))
        if cp <= 0:
            continue
        dash_line(f, x1, y, x1 + (x2 - x1) * cp, rgba(CYAN, 0.35), offset=t * 46.0)
        for k in range(2):
            q = (t * 0.55 + 0.5 * k + 0.25 * i) % 1.0
            px = x1 + (x2 - x1) * q
            if px <= x1 + (x2 - x1) * cp:
                f.glow(px, y, 16, (120, 240, 220), 0.55)
                f.circle(px, y, 2.4, rgba((220, 255, 250), 0.95))
        f.poly([(x2, y), (x2 - 6, y - 4.5), (x2 - 6, y + 4.5)], rgba(CYAN, 0.55 * cp))

    for i, (label, bn, col) in enumerate(nodes):
        p = ease_out_back(seg(t, 0.45 + 0.32 * i, 1.0 + 0.32 * i))
        if p <= 0:
            continue
        s = 0.88 + 0.12 * p
        w, h = nw * s, nh * s
        x = nx[i] + (nw - w) / 2
        y = ny + (nh - h) / 2 + 6 * (1 - p)
        f.glow(x + w / 2, y + h / 2, 110, tuple(int(c * 0.55) for c in col), 0.35 * p)
        f.rect(x, y, w, h, rgba((10, 26, 30), 0.94 * p), r=12)
        f.rect(x, y, w, h, None, r=12, outline=rgba(col, 0.6 * p), ow=1.3)
        f.circle(x + 16, y + 18, 3.4, rgba(col, 0.95 * p))
        f.text(x + 14, y + 40, label, font(MONO_B, 11), rgba(WHITE, 0.95 * p))
        f.text(x + 14, y + 70, bn, font(BANGLA_R, 13), rgba(DIM, 0.9 * p))

    cp = ease_out(seg(t, 1.5, 2.1))
    parts = ("নিজের রেন্ডারার", "নিজের এনকোডার", "নিজের কনটেইনার")
    bf = font(BANGLA_R, 14)
    widths = [f.twidth(p, bf) for p in parts]
    total_w = sum(widths) + 2 * 26 + 2 * 10
    x = (VW - total_w) / 2
    for i, (part, w) in enumerate(zip(parts, widths)):
        f.text(x, 264, part, bf, rgba(DIM, 0.92 * cp), anchor="ls")
        x += w + 10
        if i < 2:                                  # drawn arrow, not a glyph
            f.poly([(x, 253.5), (x + 9, 258), (x, 262.5)], rgba(CYAN, 0.85 * cp))
            x += 26
    f.spaced(VW / 2, 288, "PILLOW  ·  ZLIB  ·  NUMPY  ·  WAVE", font(MONO, 9),
             rgba(CYAN, 0.7 * cp), tracking=2.0, anchor="m")

    chrome(f, ctx["gp"], "03 / SOLUTION", t)
    return f


# ------------------------------------------------------------- scene 4 ------

STATS = ((600, "FRAMES", "২৫ সেকেন্ড"), (24, "FPS", "প্রতি সেকেন্ডে"),
         (48, "kHz AUDIO", "মনো, ১৬-বিট"))

BN_DIGITS = "০১২৩৪৫৬৭৮৯"


def bn_num(n):
    return "".join(BN_DIGITS[int(c)] for c in str(int(n)))


def set_stats(n_frames, total):
    """the stat card shows the file that was written, so both the builder and
    the verifier must agree on it before rendering"""
    global STATS
    STATS = ((n_frames, "FRAMES", bn_num(round(total)) + " সেকেন্ড"),
             (FPS, "FPS", "প্রতি সেকেন্ডে"),
             (A.SR // 1000, "kHz AUDIO", "মনো, ১৬-বিট"))
    return STATS


def scene_stats(t, dur, ctx):
    f = Frame((18, 15, 12), (42, 32, 20))
    f.glow(320, 300, 300, (120, 84, 24), 0.40)
    f.glow(90, 40, 180, (80, 40, 60), 0.35)

    hp = ease_out(seg(t, 0.08, 0.55))
    f.text(40 + 20 * (1 - hp), 56, "ফলাফল", font(BANGLA_B, 27), rgba(WHITE, hp), anchor="ls")
    f.spaced(42, 64, "WHATS IN THE FILE", font(MONO, 9), rgba(AMBER, 0.9 * hp), tracking=2.2)

    xs = (140, 320, 500)
    for i, ((value, unit, bn), cx) in enumerate(zip(STATS, xs)):
        p = ease_out_expo(seg(t, 0.55 + 0.22 * i, 1.65 + 0.22 * i))
        if p <= 0:
            continue
        shown = int(round(value * p))
        f.text(cx, 142, "%d" % shown, font(SANS_B, 44), rgba(WHITE, 0.96), anchor="ms")
        f.spaced(cx, 152, unit, font(MONO, 10), rgba(AMBER, 0.9), tracking=2.2, anchor="m")
        f.text(cx, 186, bn, font(BANGLA_R, 12), rgba(DIM, 0.85), anchor="ms")

    # level meter: five bars that keep moving with the music
    bw, gap = 26, 14
    x0 = (VW - (bw * 5 + gap * 4)) / 2
    base = 258
    for k in range(5):
        p = ease_out(seg(t, 0.9 + 0.1 * k, 1.5 + 0.1 * k))
        amp = 26 + 14 * math.sin(t * 3.1 + k * 0.7) ** 4
        h = amp * p
        col = mixc(AMBER, PINK, k / 4.0)
        f.rect(x0 + k * (bw + gap), base - h, bw, h, rgba(col, 0.85), r=4)
        f.rect(x0 + k * (bw + gap), base - h, bw, 3, rgba(WHITE, 0.5 * p), r=1.5)

    cap = ease_out(seg(t, 1.7, 2.3))
    f.text(VW / 2, 296, "সব মিলিয়ে মাত্র একটাই ফাইল", font(BANGLA_B, 16),
           rgba(WHITE, 0.92 * cap), anchor="ms")
    f.spaced(VW / 2, 309, FILE_LABEL, font(MONO, 9),
             rgba(CYAN, 0.6 * cap), tracking=1.6, anchor="m")

    chrome(f, ctx["gp"], "04 / RESULT", t)
    return f


# ------------------------------------------------------------- scene 5 ------

def scene_outro(t, dur, ctx):
    f = Frame((9, 11, 26), (20, 24, 52))
    f.glow(320, 150, 260, (70, 90, 190), 0.42 + 0.06 * math.sin(t * 3.0))
    film_edges(f, t, alpha=0.05)

    p = ease_out_back(seg(t, 0.1, 0.72))
    if p > 0:
        size = 74 * p
        cx, cy = VW / 2, 132
        f.rect(cx - size / 2, cy - size / 2, size, size, rgba(AMBER, 0.95), r=16 * p)
        f.poly([(cx - 10 * p, cy - 15 * p), (cx + 15 * p, cy), (cx - 10 * p, cy + 15 * p)],
               rgba(INK, 0.92))
        # expanding ring pulse
        rp = (t * 0.85) % 1.0
        f.ring(cx, cy, size * (0.62 + 0.55 * rp), rgba(AMBER, 0.5 * (1 - rp) * p), 1.5)

    tp = ease_out(seg(t, 0.5, 1.1))
    f.text(VW / 2, 214, "ধন্যবাদ", font(BANGLA_B, 34),
           rgba(WHITE, tp), anchor="ms")

    lp = ease_out(seg(t, 0.8, 1.35))
    f.spaced(VW / 2, 236, "GITHUB.COM/BDRAYHANUL/FIRST", font(MONO, 9),
             rgba(CYAN, 0.75 * lp), tracking=1.8, anchor="m")
    f.text(VW / 2, 258, "ভিডিও, ভয়েস আর সাউন্ড — সব কোড দিয়ে বানানো",
           font(BANGLA_R, 13), rgba(DIM, 0.85 * lp), anchor="ms")

    chrome(f, ctx["gp"], "05 / OUTRO", t)
    return f



# ---------------------------------------------------------------- timeline --

SCRIPT = (
    ("intro", "কোড দিয়েই পুরো একটা ভিডিও বানানো যায়।", 4.2),
    ("problem", "এখানে কোনো ভিডিও এনকোডার নেই, সাউন্ড লাইব্রেরিও নেই।", 4.6),
    ("solution", "তাই নিজেই লিখলাম এনকোডার, কনটেইনার আর সাউন্ড।", 4.8),
    ("stats", "ছশো ফ্রেম, চব্বিশ এফপিএস, আটচল্লিশ কিলোহার্টজ অডিও।", 4.8),
    ("outro", "ধন্যবাদ।", 3.0),
)

ACCENTS = (
    (0, 1.50, lambda: A.blip(1180.0, amp=0.30)),
    (0, 1.72, lambda: A.blip(1320.0, amp=0.30)),
    (0, 1.94, lambda: A.blip(1480.0, amp=0.30)),
    (1, 0.45, lambda: A.blip(880.0, amp=0.26)),
    (1, 0.69, lambda: A.blip(780.0, amp=0.24)),
    (1, 0.93, lambda: A.blip(660.0, amp=0.24)),
    (2, 0.45, lambda: A.blip(1240.0, amp=0.28)),
    (2, 0.77, lambda: A.blip(1480.0, amp=0.28)),
    (2, 1.09, lambda: A.blip(1760.0, amp=0.28)),
    (3, 0.55, lambda: A.blip(980.0, amp=0.24)),
    (3, 0.77, lambda: A.blip(1180.0, amp=0.24)),
    (3, 0.99, lambda: A.blip(1380.0, amp=0.24)),
    (4, 0.12, lambda: A.chime(1.8, 523.25, 0.55)),
)


def build_timeline():
    segs = []
    t = 0.0
    for key, text, min_dur in SCRIPT:
        voice = A.narrate(text, "vo_%s" % key, VOICE_DIR)
        dur = max(min_dur, len(voice) / A.SR + 0.95)
        frames = int(math.ceil(dur * FPS))
        dur = frames / FPS
        segs.append(dict(key=key, text=text, voice=voice, dur=dur,
                         frames=frames, start=t))
        t += dur
    return segs, t


def build_audio(segs, total):
    n = A.nsamples(total)
    voice = np.zeros(n)
    for s in segs:
        A.place(voice, s["voice"], s["start"] + 0.5)

    music = A.duck(A.build_music(total) * 0.22, voice, depth=0.72)

    sfx = np.zeros(n)
    A.place(sfx, A.riser(1.35, seed=9) * 0.55, 0.04)
    A.place(sfx, A.thud(0.55, 0.50), 0.0)
    for i, s in enumerate(segs[1:], start=1):
        A.place(sfx, A.whoosh(0.62, seed=10 + i) * 0.48, s["start"] - 0.36)
        A.place(sfx, A.thud(0.42, 0.26), s["start"] + 0.02)
    for idx, rel, fn in ACCENTS:
        A.place(sfx, fn() * 0.9, segs[idx]["start"] + rel)
    for k in range(5):                                     # meter ticks
        A.place(sfx, A.tick(amp=0.12), segs[3]["start"] + 1.0 + 0.18 * k)

    mix = music + sfx * 0.70 + voice
    mix = A.soft_clip(mix * 1.08, 1.2)

    fi, fo = A.nsamples(0.4), A.nsamples(1.0)
    mix[:fi] *= np.linspace(0, 1, fi) ** 1.5
    mix[-fo:] *= np.linspace(1, 0, fo) ** 1.3
    return A.normalize(mix, 0.92)


# -------------------------------------------------------------- compositing --

_WIPE_D = None


def wipe_mask(p):
    global _WIPE_D
    if _WIPE_D is None:
        yy, xx = np.mgrid[0:OH, 0:OW]
        _WIPE_D = xx / (OW - 1) * 0.72 + yy / (OH - 1) * 0.28
    edge = 0.17
    m = np.clip((p * (1 + 2 * edge) - _WIPE_D) / edge + 0.5, 0, 1)
    return Image.fromarray((m * 255).astype(np.uint8), "L")


def push_in(img, z):
    """slow digital zoom: continuous motion even on a held frame"""
    if z <= 1.0005:
        return img
    cw, ch = int(round(OW / z)), int(round(OH / z))
    x, y = (OW - cw) // 2, (OH - ch) // 2
    return img.crop((x, y, x + cw, y + ch)).resize((OW, OH), Image.BICUBIC)


def render_frame(t, segs, total, idx):
    s = segs[idx]
    local = t - s["start"]
    gp = min(1.0, t / total)
    img = SCENE_FNS[s["key"]](local, s["dur"], {"gp": gp}).finish()
    img = push_in(img, 1.0 + 0.035 * clamp01(local / max(1e-3, s["dur"])))

    half = TRANS / 2.0
    if local > s["dur"] - half and idx + 1 < len(segs):
        nxt = segs[idx + 1]
        p = ease_in_out(seg(local, s["dur"] - half, s["dur"] + half))
        nlocal = max(0.0, local - s["dur"])
        incoming = SCENE_FNS[nxt["key"]](nlocal, nxt["dur"], {"gp": gp}).finish()
        incoming = push_in(incoming, 1.0 + 0.035 * clamp01(nlocal / max(1e-3, nxt["dur"])))
        img = Image.composite(incoming, img, wipe_mask(p))

    # a whisper of grain for texture, then the fades
    g = grain_tile()[idx % 4]
    img = Image.blend(img, Image.merge("RGB", (g, g, g)), 0.018)
    if t < 0.45:
        img = ImageEnhance.Brightness(img).enhance(0.35 + 0.65 * (t / 0.45))
    tail = total - t
    if tail < 0.8:
        img = ImageEnhance.Brightness(img).enhance(max(0.0, tail / 0.8))
    return img


def encode_jpeg(img, quality):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, subsampling=0, optimize=True)
    return buf.getvalue()


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def encode_mp4(path, frames, wav_path, crf=18, audio_kbps=160):
    """stream raw RGB frames into x264 (no intermediate JPEG) and mux the mix"""
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("no ffmpeg available")
    cmd = [exe, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (OW, OH),
           "-r", str(FPS), "-i", "pipe:0",
           "-i", wav_path,
           "-c:v", "libx264", "-preset", "slow", "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-tune", "animation",
           "-c:a", "aac", "-b:a", "%dk" % audio_kbps, "-ac", "1", "-ar", str(A.SR),
           "-movflags", "+faststart", "-shortest", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for img in frames:
            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed")
    return os.path.getsize(path)


SCENE_FNS = {
    "intro": scene_intro,
    "problem": scene_problem,
    "solution": scene_solution,
    "stats": scene_stats,
    "outro": scene_outro,
}


# ------------------------------------------------------------------- main --

def make_contact_sheet(frames, cols=3, path=None):
    tw, th = 320, 180
    rows = int(math.ceil(len(frames) / cols))
    sheet = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
    for i, img in enumerate(frames):
        sheet.paste(img.resize((tw, th), Image.LANCZOS),
                    ((i % cols) * tw, (i // cols) * th))
    if path:
        sheet.save(path)
    return sheet


def frame_index(t, segs):
    idx = 0
    for k, s in enumerate(segs):
        if t >= s["start"] - 1e-9:
            idx = k
    return idx


def set_output_labels(use_mp4):
    """intro chips / stats footer describe the file that is actually written"""
    global CODEC_LABEL, FILE_LABEL
    if use_mp4:
        CODEC_LABEL = "H.264 720P"
        FILE_LABEL = "EXPLAINER.MP4  ·  1280x720  ·  H.264  ·  AAC"
    else:
        CODEC_LABEL = "MJPEG 720P"
        FILE_LABEL = "EXPLAINER.AVI  ·  1280x720  ·  MJPEG  ·  PCM"


def main(argv):
    global STATS

    crf = int(argv[argv.index("--crf") + 1]) if "--crf" in argv else 16
    quality = int(argv[argv.index("--quality") + 1]) if "--quality" in argv else 92
    force_avi = "--avi" in argv

    os.makedirs(OUT, exist_ok=True)
    segs, total = build_timeline()
    n_frames = int(round(total * FPS))
    set_stats(n_frames, total)

    print("timeline: %d scenes, %.2f s, %d frames @ %d fps"
          % (len(segs), total, n_frames, FPS))
    for s in segs:
        print("   +%-9s %5.2f s  voice %4.2f s  %s"
              % (s["key"], s["dur"], len(s["voice"]) / A.SR, s["text"]))

    mix = build_audio(segs, total)
    wav_path = os.path.join(OUT, "explainer.wav")
    A.write_wav(wav_path, mix)
    print("audio: %.2f s, peak %.2f, rms %.1f dBFS -> %s"
          % (len(mix) / A.SR, float(np.abs(mix).max()),
             20 * math.log10(float(np.sqrt((mix ** 2).mean())) + 1e-12), wav_path))

    poster_times = [s["start"] + min(s["dur"] - 0.45, 2.7) for s in segs]
    posters = []

    def frames():
        for i in range(n_frames):
            t = i / FPS
            img = render_frame(t, segs, total, frame_index(t, segs))
            if any(abs(t - pt) < 0.5 / FPS for pt in poster_times):
                posters.append(img)
            if i % 60 == 0:
                print("   frame %3d/%d" % (i, n_frames))
            yield img

    use_mp4 = bool(not force_avi and ffmpeg_exe())
    set_output_labels(use_mp4)
    if use_mp4:
        path = os.path.join(OUT, "explainer.mp4")
        size = encode_mp4(path, frames(), wav_path, crf=crf)
        codec = "H.264 CRF %d + AAC 160k" % crf
    else:
        path = os.path.join(OUT, "explainer.avi")
        jpegs = [encode_jpeg(img, quality) for img in frames()]
        pcm = (np.clip(mix, -1, 1) * 32767.0).astype("<i2").tobytes()
        size = write_avi_mjpeg(path, jpegs, OW, OH, FPS, pcm, A.SR)
        codec = "MJPEG q%d + PCM" % quality

    print("video: %dx%d, %d frames, %.1f MB (%s) -> %s"
          % (OW, OH, n_frames, size / 1048576.0, codec, path))

    make_contact_sheet(posters, cols=3, path=os.path.join(OUT, "contact.png"))
    print("contact sheet -> out/contact.png")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))





