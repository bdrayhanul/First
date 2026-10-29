#!/usr/bin/env python3
"""
Independent verifier for the files produced by make_video.py.

It does not trust the writer at all: it re-parses the RIFF/AVI structure,
decodes the GIF LZW stream with a separate decoder, and compares the decoded
pixels against a freshly rendered frame.
"""

import os
import struct
import sys

import make_video as mv

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


# ---------------------------------------------------------------- AVI ----

def parse_avi(path):
    blob = open(path, "rb").read()
    check(blob[:4] == b"RIFF" and blob[8:12] == b"AVI ",
          "AVI: RIFF....AVI signature")
    riff_size = struct.unpack("<I", blob[4:8])[0]
    check(riff_size == len(blob) - 8,
          "AVI: RIFF size %d == filesize-8 (%d)" % (riff_size, len(blob) - 8))

    info = {}
    pos = 12
    movi_data = b""
    movi_offset = None
    frames = []
    while pos + 8 <= len(blob):
        cid = blob[pos:pos + 4]
        size = struct.unpack("<I", blob[pos + 4:pos + 8])[0]
        data = blob[pos + 8:pos + 8 + size]
        if cid == b"LIST" and data[:4] == b"hdrl":
            p = 4
            while p + 8 <= len(data):
                sub = data[p:p + 4]
                ssize = struct.unpack("<I", data[p + 4:p + 8])[0]
                body = data[p + 8:p + 8 + ssize]
                if sub == b"avih":
                    f = struct.unpack("<IIIIIIIIII4I", body)
                    info["microsec"] = f[0]
                    info["flags"] = f[3]
                    info["frames"] = f[4]
                    info["streams"] = f[6]
                    info["width"], info["height"] = f[8], f[9]
                elif sub == b"LIST" and body[:4] == b"strl":
                    q = 4
                    while q + 8 <= len(body):
                        s2 = body[q:q + 4]
                        sz2 = struct.unpack("<I", body[q + 4:q + 8])[0]
                        b2 = body[q + 8:q + 8 + sz2]
                        if s2 == b"strh":
                            h = struct.unpack("<4s4sIHHIIIIIIIIhhhh", b2)
                            info["type"] = h[0]
                            info["handler"] = h[1]
                            info["scale"], info["rate"] = h[6], h[7]
                            info["length"] = h[9]
                        elif s2 == b"strf":
                            f2 = struct.unpack("<IiiHHIIiiII", b2)
                            info["bitcount"] = f2[4]
                            info["compression"] = f2[5]
                            info["sizeimage"] = f2[6]
                        q += 8 + sz2 + (sz2 & 1)
                p += 8 + ssize + (ssize & 1)
        elif cid == b"LIST" and data[:4] == b"movi":
            movi_offset = pos + 8
            movi_data = data[4:]
            q = 0
            while q + 8 <= len(movi_data):
                fcid = movi_data[q:q + 4]
                fsize = struct.unpack("<I", movi_data[q + 4:q + 8])[0]
                frames.append((fcid, q, movi_data[q + 8:q + 8 + fsize]))
                q += 8 + fsize + (fsize & 1)
        elif cid == b"idx1":
            info["idx_entries"] = [data[i:i + 16] for i in range(0, len(data), 16)]
        pos += 8 + size + (size & 1)

    info["frame_chunks"] = frames
    info["movi_offset"] = movi_offset
    info["movi_data"] = movi_data
    return info


def check_avi():
    print("AVI")
    info = parse_avi(os.path.join(OUT, "demo.avi"))
    n, w, h = mv.FRAMES, mv.W, mv.H
    check(info["width"] == w and info["height"] == h,
          "AVI: resolution %dx%d" % (info["width"], info["height"]))
    check(info["type"] == b"vids" and info["handler"] == b"DIB ",
          "AVI: stream is vids/DIB")
    check(info["compression"] == 0 and info["bitcount"] == 24,
          "AVI: BI_RGB, 24 bit")
    check(info["scale"] == 1 and info["rate"] == mv.FPS,
          "AVI: %d fps" % info["rate"])
    check(info["frames"] == n and info["length"] == n,
          "AVI: avih total frames %d / strh length %d" % (info["frames"], info["length"]))
    check(len(info["frame_chunks"]) == n,
          "AVI: movi holds %d frame chunks" % len(info["frame_chunks"]))
    check(len(info["idx_entries"]) == n,
          "AVI: idx1 holds %d entries" % len(info["idx_entries"]))
    check(all(c[0] == b"00db" for c in info["frame_chunks"]),
          "AVI: every frame chunk is '00db'")

    stride = w * 3
    check(all(len(c[2]) == stride * h for c in info["frame_chunks"]),
          "AVI: every frame payload is %d bytes" % (stride * h))

    # every idx1 offset must point at the matching '00db' chunk id
    ok = True
    for entry, (_, q, _) in zip(info["idx_entries"], info["frame_chunks"]):
        off = struct.unpack("<I", entry[8:12])[0]
        # offsets are measured from the 'movi' FourCC, which sits 4 bytes
        # before the payload this verifier kept
        if off - 4 != q or info["movi_data"][off - 4:off] != b"00db":
            ok = False
    check(ok, "AVI: idx1 offsets resolve to the frame chunks")

    # pixel-level check: rebuild frame 40 from the file and compare exactly
    want_i = 40
    payload = info["frame_chunks"][want_i][2]
    got = bytearray(stride * h)
    for y in range(h):
        row = payload[(h - 1 - y) * stride:(h - y) * stride]   # bottom-up -> top-down
        o = y * stride
        got[o:o + stride:3] = row[2::3]                        # BGR -> RGB
        got[o + 1:o + stride:3] = row[1::3]
        got[o + 2:o + stride:3] = row[0::3]

    cv = mv.Canvas(w, h)
    mv.render(cv, want_i, mv.FRAMES)
    check(bytes(got) == bytes(cv.buf),
          "AVI: frame %d decodes to exactly the rendered pixels" % want_i)


# ---------------------------------------------------------------- GIF ----

def lzw_decode(blob, min_code_size):
    """plain GIF LZW decoder (handles CLEAR/EOI and code-width growth)"""
    clear = 1 << min_code_size
    eoi = clear + 1
    size = min_code_size + 1
    table = None
    prev = None
    out = bytearray()
    bitpos = 0
    total = len(blob) * 8

    def fresh():
        # slots 0..clear-1 are the roots, `clear` and `eoi` stay reserved,
        # so the first *new* code is clear+2 -- exactly like the encoder
        return [bytes((i,)) for i in range(clear)] + [b"", b""]

    while bitpos + size <= total:
        code = 0
        for b in range(size):
            i = bitpos + b
            code |= ((blob[i >> 3] >> (i & 7)) & 1) << b
        bitpos += size

        if code == clear:
            table = fresh()
            size = min_code_size + 1
            prev = None
            continue
        if code == eoi:
            break
        if table is None:
            table = fresh()
        if code < len(table):
            entry = table[code]
        elif prev is not None and code == len(table):
            entry = prev + prev[:1]
        else:
            raise ValueError("corrupt LZW stream: code %d at bit %d" % (code, bitpos))
        out += entry
        if prev is not None and len(table) < 4096:
            table.append(prev + entry[:1])
        prev = entry
        if len(table) == (1 << size) and size < 12:
            size += 1
    return bytes(out)


def parse_gif(path):
    blob = open(path, "rb").read()
    check(blob[:6] in (b"GIF89a", b"GIF87a"), "GIF: signature %r" % blob[:6])
    w, h, packed, bg, aspect = struct.unpack("<HHBBB", blob[6:13])
    check(bool(packed & 0x80), "GIF: global colour table present")
    gct_len = 2 << (packed & 0x07)
    pos = 13 + gct_len * 3
    gct = blob[13:pos]
    frames = []
    delays = []
    loop_ext = False
    while pos < len(blob):
        marker = blob[pos]
        if marker == 0x3B:
            pos += 1
            break
        if marker == 0x21:
            label = blob[pos + 1]
            pos += 2
            if label == 0xF9:
                size = blob[pos]
                delays.append(struct.unpack("<H", blob[pos + 2:pos + 4])[0])
                pos += 1 + size
            elif label == 0xFF:
                size = blob[pos]
                if blob[pos + 1:pos + 1 + size] == b"NETSCAPE2.0":
                    loop_ext = True
                pos += 1 + size
            else:
                pos += 1
            while blob[pos]:                        # skip sub-block payloads
                pos += 1 + blob[pos]
            pos += 1
        elif marker == 0x2C:
            left, top, fw, fh, flags = struct.unpack("<HHHHB", blob[pos + 1:pos + 10])
            pos += 10
            if flags & 0x80:
                pos += (2 << (flags & 0x07)) * 3
            mcs = blob[pos]
            pos += 1
            data = bytearray()
            while blob[pos]:
                n = blob[pos]
                data += blob[pos + 1:pos + 1 + n]
                pos += 1 + n
            pos += 1
            frames.append((left, top, fw, fh, mcs, bytes(data)))
        else:
            raise ValueError("unexpected GIF block 0x%02X at %d" % (marker, pos))
    return dict(w=w, h=h, gct=gct, frames=frames, delays=delays,
                loop=loop_ext, tail=pos)


def check_gif():
    print("GIF")
    g = parse_gif(os.path.join(OUT, "demo.gif"))
    w, h = mv.GW, mv.GH
    n_gif = (mv.FRAMES + 1) // 2
    check(g["w"] == w and g["h"] == h, "GIF: canvas is %dx%d" % (g["w"], g["h"]))
    check(len(g["frames"]) == n_gif, "GIF: %d image frames" % len(g["frames"]))
    check(g["loop"], "GIF: NETSCAPE2.0 looping extension")
    check(len(g["delays"]) == n_gif and set(g["delays"]) == {6},
          "GIF: per-frame delay %s (1/100 s)" % sorted(set(g["delays"])))
    check(all(f[4] == 8 for f in g["frames"]), "GIF: LZW min code size 8")
    check(all(f[2] == w and f[3] == h for f in g["frames"]),
          "GIF: every frame covers the full canvas")

    bad = 0
    for k, (_, _, fw, fh, mcs, data) in enumerate(g["frames"]):
        idx = lzw_decode(data, mcs)
        if len(idx) != fw * fh:
            bad += 1
            continue
        cv = mv.Canvas(fw, fh)
        mv.render(cv, k * 2, mv.FRAMES)
        if idx != mv.gif_indices(cv):
            bad += 1
    check(bad == 0, "GIF: all %d frames decode back to the rendered pixels" % n_gif)
    check(g["gct"][:3] == b"\x00\x00\x00" and g["gct"][-3:] == b"\xff\xff\xff",
          "GIF: 216-colour cube + 40-step gray ramp")


# ---------------------------------------------------------------- PNG ----

def check_png():
    print("PNG")
    import zlib
    blob = open(os.path.join(OUT, "poster.png"), "rb").read()
    check(blob[:8] == b"\x89PNG\r\n\x1a\n", "PNG: signature")
    pos = 8
    w = h = None
    idat = b""
    crc_ok = True
    while pos < len(blob):
        size = struct.unpack(">I", blob[pos:pos + 4])[0]
        tag = blob[pos + 4:pos + 8]
        body = blob[pos + 8:pos + 8 + size]
        crc = struct.unpack(">I", blob[pos + 8 + size:pos + 12 + size])[0]
        if crc != (zlib.crc32(tag + body) & 0xFFFFFFFF):
            crc_ok = False
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + size
    check(crc_ok, "PNG: every chunk CRC32 is valid")
    check(w == mv.W and h == mv.H, "PNG: %dx%d" % (w, h))
    raw = zlib.decompress(idat)
    check(len(raw) == (mv.W * 3 + 1) * mv.H, "PNG: decompressed scanline bytes")
    cv = mv.Canvas(mv.W, mv.H)
    mv.render(cv, mv.FRAMES // 2, mv.FRAMES)
    rows_ok = all(raw[y * (mv.W * 3 + 1)] == 0 for y in range(mv.H))
    body_ok = all(raw[y * (mv.W * 3 + 1) + 1:(y + 1) * (mv.W * 3 + 1)] ==
                  bytes(cv.buf[y * mv.W * 3:(y + 1) * mv.W * 3])
                  for y in range(mv.H))
    check(rows_ok and body_ok,
          "PNG: pixels match rendered frame %d" % (mv.FRAMES // 2))


def main():
    check_avi()
    check_gif()
    check_png()
    print()
    if failures:
        print("FAILED (%d)" % len(failures))
        for f in failures:
            print("  - " + f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
