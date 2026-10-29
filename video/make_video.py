#!/usr/bin/env python3
"""
Make a short animated video using nothing but the Python standard library.

Outputs (in ./out):
  demo.avi    384x216, 30 fps, 60 frames, uncompressed 24-bit BGR (RIFF/AVI)
  demo.gif    256x144, 15 fps, 30 frames, GIF89a with a hand-written LZW encoder
  poster.png  one frame as PNG (zlib)

No ffmpeg, no Pillow, no numpy -- every byte of every container is produced here.
"""

import math
import os
import struct
import sys
import zlib


# --------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------


def clamp8(v):
    return 0 if v < 0 else (255 if v > 255 else int(v))


def mix(a, b, t):
    return (clamp8(a[0] + (b[0] - a[0]) * t),
            clamp8(a[1] + (b[1] - a[1]) * t),
            clamp8(a[2] + (b[2] - a[2]) * t))


def hsv(h, s, v):
    """h in [0,1), s/v in [0,1] -> (r,g,b)"""
    i = int(h * 6.0) % 6
    f = h * 6.0 - int(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    r, g, b = [(v, t, p), (q, v, p), (p, v, t),
               (p, q, v), (t, p, v), (v, p, q)][i]
    return (clamp8(r * 255), clamp8(g * 255), clamp8(b * 255))


# --------------------------------------------------------------------------
# canvas: a flat RGB byte buffer with the few primitives this demo needs
# --------------------------------------------------------------------------


class Canvas:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.buf = bytearray(w * h * 3)

    def fill(self, rgb):
        self.buf[:] = bytes(rgb) * (self.w * self.h)

    def px(self, x, y, rgb):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i] = rgb[0]
            self.buf[i + 1] = rgb[1]
            self.buf[i + 2] = rgb[2]

    def rect(self, x0, y0, x1, y1, rgb):
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(self.w, int(x1)), min(self.h, int(y1))
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(rgb) * (x1 - x0)
        for y in range(y0, y1):
            i = (y * self.w + x0) * 3
            self.buf[i:i + len(row)] = row

    def vgrad(self, top, bottom, y0=0, y1=None):
        y1 = self.h if y1 is None else min(self.h, y1)
        span = max(1, y1 - y0 - 1)
        for y in range(max(0, y0), y1):
            self.rect(0, y, self.w, y + 1, mix(top, bottom, (y - y0) / span))

    def disc(self, cx, cy, r, rgb):
        if r <= 0:
            return
        r2 = r * r
        for dy in range(-int(r), int(r) + 1):
            y = int(cy) + dy
            span = int(math.sqrt(max(0.0, r2 - dy * dy)))
            self.rect(int(cx) - span, y, int(cx) + span + 1, y + 1, rgb)

    def ring(self, cx, cy, r, thickness, rgb):
        r_out2 = r * r
        r_in2 = max(0.0, (r - thickness) ** 2)
        for dy in range(-int(r), int(r) + 1):
            y = int(cy) + dy
            d2 = dy * dy
            if d2 > r_out2:
                continue
            outer = int(math.sqrt(r_out2 - d2))
            inner = int(math.sqrt(max(0.0, r_in2 - d2)))
            if inner:
                self.rect(int(cx) - outer, y, int(cx) - inner, y + 1, rgb)
                self.rect(int(cx) + inner + 1, y, int(cx) + outer + 1, y + 1, rgb)
            else:
                self.rect(int(cx) - outer, y, int(cx) + outer + 1, y + 1, rgb)

    def text(self, x, y, s, rgb, scale=1):
        x, y = int(x), int(y)
        for ch in s.upper():
            glyph = FONT.get(ch, FONT["?"])
            for ry, bits in enumerate(glyph):
                for rx in range(GLYPH_W):
                    if bits & (1 << (GLYPH_W - 1 - rx)):
                        self.rect(x + rx * scale, y + ry * scale,
                                  x + (rx + 1) * scale, y + (ry + 1) * scale, rgb)
            x += ADVANCE * scale

    def scaled(self, nw, nh):
        """nearest-neighbour downscale to a new canvas"""
        out = Canvas(nw, nh)
        sx = self.w / nw
        sy = self.h / nh
        src, dst = self.buf, out.buf
        for y in range(nh):
            base = (int(y * sy) * self.w) * 3
            o = (y * nw) * 3
            for x in range(nw):
                i = base + int(x * sx) * 3
                dst[o] = src[i]
                dst[o + 1] = src[i + 1]
                dst[o + 2] = src[i + 2]
                o += 3
        return out


# --------------------------------------------------------------------------
# a tiny 5x7 bitmap font (one string per glyph: 7 rows of 5 bits)
# --------------------------------------------------------------------------

_FONT_ROWS = {
    "A": "01110 10001 10001 11111 10001 10001 10001",
    "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110",
    "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111",
    "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "11111 00100 00100 00100 00100 00100 11111",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001",
    "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001",
    "N": "10001 11001 10101 10011 10001 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101",
    "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 11011 10001",
    "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010",
    "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100",
    " ": "00000 00000 00000 00000 00000 00000 00000",
    ".": "00000 00000 00000 00000 00000 01100 01100",
    ":": "00000 01100 01100 00000 01100 01100 00000",
    "-": "00000 00000 00000 11111 00000 00000 00000",
    "+": "00000 00100 00100 11111 00100 00100 00000",
    "=": "00000 00000 11111 00000 11111 00000 00000",
    "/": "00001 00010 00010 00100 01000 01000 10000",
    "!": "00100 00100 00100 00100 00100 00000 00100",
    "?": "01110 10001 00001 00110 00100 00000 00100",
    "(": "00010 00100 01000 01000 01000 00100 00010",
    ")": "01000 00100 00010 00010 00010 00100 01000",
    "*": "00000 00100 10101 01110 10101 00100 00000",
    "#": "01010 01010 11111 01010 11111 01010 01010",
    "%": "11001 11010 00010 00100 01000 01011 10011",
}

FONT = {ch: [int(row, 2) for row in rows.split()] for ch, rows in _FONT_ROWS.items()}
GLYPH_W, GLYPH_H, ADVANCE = 5, 7, 6


def text_width(s, scale=1):
    return max(0, (len(s) * ADVANCE - 1) * scale)


# --------------------------------------------------------------------------
# the animation: gradient sky, three bouncing balls, text, progress bar
# --------------------------------------------------------------------------

W, H, FPS, FRAMES = 384, 216, 30, 60
GW, GH = 320, 180          # the GIF is rendered natively at this size

TITLE = "CODE MAKES VIDEO"
SUBTITLE = "PURE PYTHON - NO FFMPEG"
TAGLINE = "STDLIB ONLY"


def render(cv, i, n):
    """draw frame `i` of `n`; every coordinate is derived from the canvas size"""
    w, h = cv.w, cv.h
    t = i / max(1, n - 1)
    ang = 2.0 * math.pi * t

    # --- background: hue-shifting vertical gradient + soft scanlines
    top = hsv(0.62 + 0.12 * math.sin(ang), 0.75, 0.30)
    bot = hsv(0.50 + 0.14 * math.sin(ang + 1.3), 0.85, 0.60)
    cv.vgrad(top, bot)
    step = max(4, h // 27)
    for y in range(0, h, step):
        c = mix(top, bot, y / (h - 1))
        cv.rect(0, y, w, y + 1,
                (max(0, c[0] - 12), max(0, c[1] - 12), max(0, c[2] - 12)))

    # --- three bouncing balls (before the text, so the text stays legible)
    floor_y = h * 0.80
    specs = ((0.20, 0.055, 0.00, 0.55), (0.50, 0.078, 0.33, 0.42),
             (0.80, 0.046, 0.66, 0.62))
    for bx, frac, phase, hue in specs:
        rad = max(4.0, h * frac)
        cyc = 2.0 * ang + phase * 2.0 * math.pi
        height = abs(math.sin(cyc)) * (h * 0.40)
        cx = bx * w + 0.016 * w * math.sin(ang * 3 + phase * 6)
        cy = floor_y - rad - height
        col = hsv((hue + 0.06 * t) % 1.0, 0.75, 1.0)
        for k, fade in ((1, 0.45), (2, 0.22)):          # motion trail
            h2 = abs(math.sin(cyc - 0.18 * k)) * (h * 0.40)
            cx2 = bx * w + 0.016 * w * math.sin((ang - 0.03 * k) * 3 + phase * 6)
            cv.disc(cx2, floor_y - rad - h2, rad * 0.8,
                    mix(mix(top, bot, 0.5), col, fade))
        cv.disc(cx, cy, rad, col)
        cv.disc(cx - rad * 0.35, cy - rad * 0.35, rad * 0.30,
                mix(col, (255, 255, 255), 0.65))

    # --- title with drop shadow
    ts = 2 if w >= 280 else 1
    ty = int(h * 0.135)
    tx = (w - text_width(TITLE, ts)) // 2
    cv.text(tx + ts, ty + ts, TITLE, (10, 14, 26), ts)
    cv.text(tx, ty, TITLE,
            mix((255, 236, 160), (255, 255, 255), 0.5 * (1 - t)), ts)

    sy = ty + 8 * ts + 5
    cv.text((w - text_width(SUBTITLE, 1)) // 2, sy, SUBTITLE, (222, 250, 255), 1)

    # --- progress bar
    bx0 = int(w * 0.06)
    bx1 = w - bx0
    by = int(h * 0.87)
    bar_h = max(3, h // 54)
    cv.rect(bx0, by, bx1, by + bar_h, (24, 30, 46))
    fill_x = bx0 + int((bx1 - bx0 - bar_h) * t)
    bar_col = hsv((0.11 + 0.05 * math.cos(ang)) % 1.0, 0.85, 1.0)
    cv.rect(bx0, by, fill_x, by + bar_h, bar_col)
    cv.disc(fill_x + bar_h // 2, by + bar_h // 2, bar_h // 2 + 0.5, bar_col)

    # --- HUD text
    cv.text(bx0, by - 12, "FRAME %02d/%02d" % (i + 1, n), (238, 242, 250), 1)
    cv.text(bx1 - text_width(TAGLINE, 1), by - 12, TAGLINE, (206, 232, 246), 1)


# --------------------------------------------------------------------------
# AVI container writer (RIFF / AVI, uncompressed 24-bit BGR 'DIB ' frames)
# --------------------------------------------------------------------------


def _chunk(cid, data):
    out = cid + struct.pack("<I", len(data)) + data
    if len(data) & 1:
        out += b"\x00"
    return out


def write_avi(path, frames, w, h, fps):
    """frames: list of raw RGB byte strings (w*h*3, top-down)"""
    stride = w * 3
    pad = (4 - stride % 4) % 4
    frame_bytes = (stride + pad) * h
    n = len(frames)

    avih = struct.pack("<IIIIIIIIII4I",
                       int(1000000 / fps),   # dwMicroSecPerFrame
                       stride * h * fps,     # dwMaxBytesPerSec
                       0,                    # dwPaddingGranularity
                       0x10,                 # dwFlags: AVIF_HASINDEX
                       n, 0, 1, frame_bytes, w, h, 0, 0, 0, 0)

    strh = struct.pack("<4s4sIHHIIIIIIIIhhhh",
                       b"vids", b"DIB ", 0, 0, 0, 0,
                       1,           # dwScale
                       fps,         # dwRate -> fps = rate/scale
                       0,           # dwStart
                       n,           # dwLength (frames)
                       frame_bytes,
                       0xFFFFFFFF,  # dwQuality
                       0,           # dwSampleSize
                       0, 0, w, h)  # rcFrame

    strf = struct.pack("<IiiHHIIiiII",
                       40, w, h, 1, 24, 0, stride * h, 0, 0, 0, 0)

    strl = _chunk(b"strh", strh) + _chunk(b"strf", strf)
    hdrl = _chunk(b"LIST", b"hdrl" + _chunk(b"avih", avih) +
                  _chunk(b"LIST", b"strl" + strl))

    movi_data = bytearray()
    index = bytearray()
    for rgb in frames:
        rows = bytearray()
        for y in range(h - 1, -1, -1):          # AVI is bottom-up BGR
            row = rgb[y * stride:(y + 1) * stride]
            bgr = bytearray(stride)
            bgr[0::3] = row[2::3]
            bgr[1::3] = row[1::3]
            bgr[2::3] = row[0::3]
            rows += bgr + b"\x00" * pad
        pos = 4 + len(movi_data)                # offset from the 'movi' FourCC
        movi_data += _chunk(b"00db", bytes(rows))
        index += b"00db" + struct.pack("<III", 0x10, pos, frame_bytes)

    body = (b"AVI " + hdrl +
            _chunk(b"LIST", b"movi" + bytes(movi_data)) +
            _chunk(b"idx1", bytes(index)))
    blob = b"RIFF" + struct.pack("<I", len(body)) + body
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)


# --------------------------------------------------------------------------
# PNG writer (zlib deflate, 8-bit truecolour)
# --------------------------------------------------------------------------


def write_png(path, w, h, rgb):
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)                           # filter type 0
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    blob = (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) +
            chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)



# --------------------------------------------------------------------------
# GIF container writer (GIF89a + hand-rolled LZW)
# --------------------------------------------------------------------------


_CUBE_LEVELS = (0, 51, 102, 153, 204, 255)
_GRAY_BASE = 216                       # first index of the gray ramp


def gif_palette():
    """216-entry RGB cube + 40 neutral grays: cheap, and keeps thin text crisp"""
    pal = bytearray()
    for r in _CUBE_LEVELS:
        for g in _CUBE_LEVELS:
            for b in _CUBE_LEVELS:
                pal += bytes((r, g, b))
    for i in range(256 - _GRAY_BASE):
        v = i * 255 // (256 - _GRAY_BASE - 1)
        pal += bytes((v, v, v))
    return bytes(pal)


def gif_indices(cv):
    buf = cv.buf
    idx = bytearray(cv.w * cv.h)
    for p in range(cv.w * cv.h):
        i = p * 3
        r, g, b = buf[i], buf[i + 1], buf[i + 2]
        if max(r, g, b) - min(r, g, b) <= 20:      # nearly neutral -> gray ramp
            v = (r + g + b) // 3
            idx[p] = _GRAY_BASE + min(39, (v * 40) // 256)
        else:                                       # nearest point of the cube
            idx[p] = ((r * 5 + 127) // 255) * 36 + \
                     ((g * 5 + 127) // 255) * 6 + \
                     ((b * 5 + 127) // 255)
    return idx


class _BitWriter:
    """LSB-first bit packer (the order GIF's LZW expects)"""

    __slots__ = ("buf", "cur", "n")

    def __init__(self):
        self.buf = bytearray()
        self.cur = 0
        self.n = 0

    def write(self, code, size):
        self.cur |= code << self.n
        self.n += size
        while self.n >= 8:
            self.buf.append(self.cur & 0xFF)
            self.cur >>= 8
            self.n -= 8

    def flush(self):
        if self.n:
            self.buf.append(self.cur & 0xFF)
            self.cur = 0
            self.n = 0


def lzw_encode(data):
    """GIF-flavoured LZW with fixed 9-bit codes.

    The table is flushed with a CLEAR code as soon as the next free code
    would reach 512, so the code width never has to grow: every code in the
    stream stays <= 511 and the output is easy to decode/verify."""
    CLEAR, EOI, FIRST = 256, 257, 258
    bw = _BitWriter()
    bw.write(CLEAR, 9)
    if not data:
        bw.write(EOI, 9)
        bw.flush()
        return bytes(bw.buf)

    table = {}
    next_code = FIRST
    w = data[0]
    for k in data[1:]:
        key = (w << 8) | k
        code = table.get(key)
        if code is not None:
            w = code
            continue
        bw.write(w, 9)
        table[key] = next_code
        next_code += 1
        if next_code == 512:            # keep every emitted code inside 9 bits
            bw.write(CLEAR, 9)
            table.clear()
            next_code = FIRST
        w = k
    bw.write(w, 9)
    bw.write(EOI, 9)
    bw.flush()
    return bytes(bw.buf)


def write_gif(path, canvases, delay_cs):
    w, h = canvases[0].w, canvases[0].h
    out = bytearray(b"GIF89a")
    out += struct.pack("<HHBBB", w, h, 0xF7, 0, 0)       # 256-colour global table
    out += gif_palette()
    out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01" + struct.pack("<H", 0) + b"\x00"
    for cv in canvases:
        out += b"\x21\xF9\x04\x04" + struct.pack("<H", delay_cs) + b"\x00\x00"
        out += b"\x2C" + struct.pack("<HHHH", 0, 0, w, h) + b"\x00"
        out += b"\x08"                                   # LZW minimum code size
        data = lzw_encode(gif_indices(cv))
        for i in range(0, len(data), 255):
            block = data[i:i + 255]
            out += bytes((len(block),)) + block
        out += b"\x00"
    out += b"\x3B"
    with open(path, "wb") as fh:
        fh.write(bytes(out))
    return len(out)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(here, "out")
    os.makedirs(out_dir, exist_ok=True)

    cv = Canvas(W, H)
    frames = []
    for i in range(FRAMES):
        render(cv, i, FRAMES)
        frames.append(bytes(cv.buf))

    gif_frames = []
    for i in range(0, FRAMES, 2):               # the GIF runs at half the fps
        gcv = Canvas(GW, GH)
        render(gcv, i, FRAMES)                  # native size: no resampling
        gif_frames.append(gcv)

    avi_path = os.path.join(out_dir, "demo.avi")
    gif_path = os.path.join(out_dir, "demo.gif")
    png_path = os.path.join(out_dir, "poster.png")

    avi_size = write_avi(avi_path, frames, W, H, FPS)
    gif_size = write_gif(gif_path, gif_frames, int(100 / (FPS / 2)))
    png_size = write_png(png_path, W, H, frames[FRAMES // 2])

    print("demo.avi    %4dx%-4d %2d fps %3d frames  %8.2f MB" %
          (W, H, FPS, FRAMES, avi_size / 1048576.0))
    print("demo.gif    %4dx%-4d %2d fps %3d frames  %8.2f MB" %
          (GW, GH, FPS // 2, len(gif_frames), gif_size / 1048576.0))
    print("poster.png  %4dx%-4d %8.2f MB" % (W, H, png_size / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())


