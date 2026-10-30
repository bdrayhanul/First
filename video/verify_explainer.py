#!/usr/bin/env python3
"""
Independent checks on out/explainer.avi:

  * re-parses the RIFF tree (two streams: MJPEG video + PCM audio)
  * decodes frames straight out of the file and checks they look like pictures
  * rebuilds the PCM track and checks level, silence and A/V length match
  * writes out/audio.png (waveform + spectrogram) as visual evidence
"""

import io
import os
import re
import struct
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw

import audio_synth as A
import explainer as E

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
MP4 = os.path.join(OUT, "explainer.mp4")
AVI = os.path.join(OUT, "explainer.avi")

failures = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def find_lists(blob, p, end, kind):
    """positions of LIST chunks whose type == kind, at any depth"""
    res = []
    while p + 12 <= end:
        cid = blob[p:p + 4]
        size = struct.unpack("<I", blob[p + 4:p + 8])[0]
        if cid == b"LIST":
            if blob[p + 8:p + 12] == kind:
                res.append((p + 8, p + 12, p + 8 + size))
            res += find_lists(blob, p + 12, p + 8 + size, kind)
        p += 8 + size + (size & 1)
    return res


def parse(path):
    blob = open(path, "rb").read()
    info = {"size": len(blob), "streams": []}

    check(blob[:4] == b"RIFF" and blob[8:12] == b"AVI ", "AVI: RIFF....AVI signature")
    check(struct.unpack("<I", blob[4:8])[0] == len(blob) - 8,
          "AVI: RIFF size == filesize-8 (%d)" % (len(blob) - 8))

    hdrl = find_lists(blob, 12, len(blob), b"hdrl")[0]
    for _, ss, se in find_lists(blob, hdrl[1], hdrl[2], b"strl"):
        p, strh, strf = ss, None, None
        while p + 8 <= se:
            cid = blob[p:p + 4]
            size = struct.unpack("<I", blob[p + 4:p + 8])[0]
            if cid == b"strh":
                strh = blob[p + 8:p + 8 + size]
            elif cid == b"strf":
                strf = blob[p + 8:p + 8 + size]
            p += 8 + size + (size & 1)
        if strh[:4] == b"vids":
            f = struct.unpack("<4s4sIHHIIIIIIIIhhhh", strh)
            sf = struct.unpack("<IiiHHIIiiII", strf)
            info["streams"].append(dict(
                kind="vids", handler=f[1].decode("latin-1"), scale=f[6], rate=f[7],
                length=f[9], width=sf[1], height=sf[2], bitcount=sf[4],
                compression=struct.pack("<I", sf[5]), sizeimage=sf[6]))
        elif strh[:4] == b"auds":
            f = struct.unpack("<4s4sIHHIIIIIIIIhhhh", strh)
            sf = struct.unpack("<HHIIHH", strf)
            info["streams"].append(dict(
                kind="auds", scale=f[6], rate=f[7], length=f[9], format=sf[0],
                channels=sf[1], rate_hz=sf[2], bytes_per_sec=sf[3],
                block_align=sf[4], bits=sf[5]))

    p = 12
    while p + 8 <= len(blob):
        cid = blob[p:p + 4]
        size = struct.unpack("<I", blob[p + 4:p + 8])[0]
        if cid == b"LIST" and blob[p + 8:p + 12] == b"movi":
            vids, auds = [], []
            q = p + 12
            while q + 8 <= p + 8 + size:
                sid = blob[q:q + 4]
                ssize = struct.unpack("<I", blob[q + 4:q + 8])[0]
                (vids if sid == b"00db" else auds).append(blob[q + 8:q + 8 + ssize])
                q += 8 + ssize + (ssize & 1)
            info["video"], info["audio"] = vids, auds
        elif cid == b"idx1":
            data = blob[p + 8:p + 8 + size]
            info["idx"] = [data[i:i + 16] for i in range(0, len(data), 16)]
        p += 8 + size + (size & 1)
    return info, blob


def ff(*args):
    exe = E.ffmpeg_exe()
    return subprocess.run([exe, "-hide_banner", "-loglevel", "error"] + list(args),
                          check=True, capture_output=True)


def ff_info(path):
    exe = E.ffmpeg_exe()
    return subprocess.run([exe, "-hide_banner", "-i", path],
                          capture_output=True, text=True).stderr


def decode_frames(path, indices):
    """pull exact frame numbers out of the encode, as PNG bytes"""
    out = {}
    for i in indices:
        png = ff("-i", path, "-vf", "select=eq(n\\,%d)" % i, "-frames:v", "1",
                 "-f", "image2pipe", "-vcodec", "png", "pipe:1").stdout
        out[i] = png
    return out


def check_mp4():
    print("MP4")
    info = ff_info(MP4)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
    secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    check("Video: h264" in info, "MP4: H.264 video stream")
    check("%dx%d" % (E.OW, E.OH) in info, "MP4: %dx%d video" % (E.OW, E.OH))
    check("%d fps" % E.FPS in info, "MP4: %d fps" % E.FPS)
    check("yuv420p" in info, "MP4: yuv420p (plays everywhere)")
    check("Audio: aac" in info and "%d Hz" % A.SR in info and "mono" in info,
          "MP4: AAC %d Hz mono audio" % A.SR)

    segs, total = E.build_timeline()
    n_frames = int(round(total * E.FPS))
    E.set_stats(n_frames, total)          # the stat card must match the file
    check(abs(secs - n_frames / E.FPS) < 0.06,
          "MP4: duration %.3f s == %.3f s of frames (A/V in sync)"
          % (secs, n_frames / E.FPS))

    picks = [n_frames // 8, n_frames // 2, 7 * n_frames // 8]
    decoded = decode_frames(MP4, picks)
    worst = 99.0
    for i in picks:
        dec = np.asarray(Image.open(io.BytesIO(decoded[i])).convert("RGB"), dtype=np.float64)
        t = i / E.FPS
        ref = np.asarray(E.render_frame(t, segs, total, E.frame_index(t, segs)),
                         dtype=np.float64)
        if dec.shape != ref.shape:
            check(False, "MP4: frame %d has the wrong size %s" % (i, dec.shape))
            continue
        mse = float(((dec - ref) ** 2).mean())
        psnr = 10 * np.log10(255.0 ** 2 / max(mse, 1e-9))
        worst = min(worst, psnr)
        print("        frame %3d  %dx%d  PSNR %5.2f dB  mean|err| %.2f"
              % (i, dec.shape[1], dec.shape[0], psnr, np.abs(dec - ref).mean()))
    check(worst > 36.0, "MP4: every sampled frame is >= 36 dB PSNR vs the render")

    wav = ff("-i", MP4, "-vn", "-ac", "1", "-ar", str(A.SR),
             "-c:a", "pcm_s16le", "-f", "wav", "pipe:1").stdout
    with wave.open(io.BytesIO(wav)) as w:
        aac = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768.0
    mix = A.read_wav(os.path.join(OUT, "explainer.wav"))
    n = min(len(aac), len(mix))
    corr = float(np.corrcoef(aac[:n], mix[:n])[0, 1])
    check(corr > 0.99, "MP4: decoded AAC matches the mix (correlation %.5f)" % corr)
    check(abs(len(aac) - len(mix)) / A.SR < 0.05,
          "MP4: audio track length %.3f s vs mix %.3f s"
          % (len(aac) / A.SR, len(mix) / A.SR))
    check(abs(aac[:n].std() - mix[:n].std()) < 0.02,
          "MP4: AAC level preserved (%.3f vs %.3f)" % (aac[:n].std(), mix[:n].std()))
    return mix

    print("AVI")
    info, blob = parse(AVI)
    kinds = [s["kind"] for s in info["streams"]]
    check(kinds == ["vids", "auds"], "AVI: two streams, %s" % kinds)
    v, a = info["streams"]
    n = len(info["video"])

    check(v["handler"] == "MJPG", "AVI: video handler is MJPG")
    check(v["compression"] == b"MJPG", "AVI: strf biCompression == MJPG")
    check((v["width"], v["height"]) == (E.OW, E.OH),
          "AVI: %dx%d video" % (v["width"], v["height"]))
    check(v["scale"] == 1 and v["rate"] == E.FPS, "AVI: %d fps" % v["rate"])
    check(v["length"] == n, "AVI: strh length %d == %d chunks in movi" % (v["length"], n))

    check(a["format"] == 1 and a["channels"] == 1 and a["bits"] == 16,
          "AVI: audio is 16-bit mono PCM")
    check(a["rate_hz"] == A.SR, "AVI: audio is %d Hz" % a["rate_hz"])
    check(a["block_align"] == 2 and a["bytes_per_sec"] == A.SR * 2,
          "AVI: PCM block align / byte rate consistent")

    check(len(info["audio"]) == n and len(info["idx"]) == 2 * n,
          "AVI: %d video + %d audio chunks, %d index entries"
          % (n, len(info["audio"]), len(info["idx"])))
    order = [e[:4] for e in info["idx"]]
    check(order[:4] == [b"00db", b"01wb", b"00db", b"01wb"],
          "AVI: index is interleaved video/audio")

    ok = True
    movi_pos = None
    for p, _, _ in find_lists(blob, 12, len(blob), b"movi"):
        movi_pos = p
        break
    for e in info["idx"]:
        off = struct.unpack("<I", e[8:12])[0]
        abs_pos = movi_pos + off              # offsets are from the 'movi' FourCC
        if blob[abs_pos:abs_pos + 4] != e[:4]:
            ok = False
    check(ok, "AVI: idx1 offsets resolve to real chunks")

    picks = [n // 8, n // 4, n // 2, 3 * n // 4, 7 * n // 8]
    good = True
    for i in picks:
        img = Image.open(io.BytesIO(info["video"][i])).convert("RGB")
        arr = np.asarray(img, dtype=np.float32)
        mean, std = float(arr.mean()), float(arr.std())
        print("        frame %3d  %s  mean %5.1f  std %4.1f" % (i, img.size, mean, std))
        if img.size != (E.OW, E.OH) or std < 6.0 or mean < 3.0:
            good = False
    check(good, "AVI: frames decode out of the container (size/brightness/contrast)")

    # the film opens and closes on black, by design
    first = np.asarray(Image.open(io.BytesIO(info["video"][0])), dtype=np.float32)
    last = np.asarray(Image.open(io.BytesIO(info["video"][n - 1])), dtype=np.float32)
    check(first.mean() < 20 and last.mean() < 12,
          "AVI: fade in / fade out (first mean %.1f, last mean %.1f)"
          % (first.mean(), last.mean()))

    pcm = b"".join(info["audio"])
    spf = A.SR // E.FPS
    check(len(pcm) == n * spf * 2,
          "AVI: %d audio bytes == %d frames x %d samples x 2 bytes" % (len(pcm), n, spf))
    check(all(len(c) == spf * 2 for c in info["audio"]),
          "AVI: every audio chunk holds exactly %d samples" % spf)

    x = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
    peak = float(np.abs(x).max())
    rms = float(np.sqrt((x ** 2).mean()))
    check(peak < 0.999, "AVI: no clipped samples (peak %.3f)" % peak)
    check(0.03 < rms < 0.5, "AVI: healthy level (rms %.3f)" % rms)
    check(abs(len(x) / A.SR - n / E.FPS) < 1e-9,
          "AVI: audio %.3f s == video %.3f s (A/V in sync)"
          % (len(x) / A.SR, n / E.FPS))
    return info, x, pcm


def check_wav():
    print("WAV")
    path = os.path.join(OUT, "explainer.wav")
    with wave.open(path, "rb") as w:
        params = (w.getnchannels(), w.getsampwidth(), w.getframerate())
        raw = w.readframes(w.getnframes())
    segs, total = E.build_timeline()
    check(params == (1, 2, A.SR), "WAV: mono, 16-bit, %d Hz" % A.SR)
    check(abs(len(raw) / 2 / A.SR - total) < 1e-6,
          "WAV: %.3f s long, matches the timeline" % (len(raw) / 2 / A.SR))
    return A.read_wav(path)


def check_voice(x):
    print("VOICE")
    segs, total = E.build_timeline()
    for s in segs:
        i0 = int((s["start"] + 0.5) * A.SR)
        seg = x[i0:i0 + len(s["voice"])]
        energy = float(np.sqrt((seg ** 2).mean()))
        check(energy > 0.05, "speech present in '%-8s' at %5.2f s (rms %.3f)"
              % (s["key"], s["start"] + 0.5, energy))

    a = segs[0]
    g0 = a["start"] + 0.5 + len(a["voice"]) / A.SR
    g1 = segs[1]["start"] + 0.5
    if g1 - g0 > 0.3:
        seg = x[int(g0 * A.SR):int(g1 * A.SR)]
        lvl = float(np.sqrt((seg ** 2).mean()))
        check(0.01 < lvl < 0.2,
              "music continues (ducked) between lines (rms %.3f)" % lvl)


def audio_png(x, path):
    """waveform above, log-frequency spectrogram below: one glance proves the mix"""
    W, HW, HS = 900, 150, 260
    img = Image.new("RGB", (W, HW + HS + 26), (10, 12, 20))
    d = ImageDraw.Draw(img)

    d.line([(0, HW // 2), (W, HW // 2)], fill=(38, 44, 66))
    step = max(1, len(x) // (W * 8))
    nb = len(x) // step // W
    blk = x[:nb * W * step].reshape(nb, W, step)
    hi, lo = blk.max(axis=2).ravel(), blk.min(axis=2).ravel()
    for i in range(W):
        d.line([(i, HW // 2 - int(hi[i] * HW * 0.47)),
                (i, HW // 2 - int(lo[i] * HW * 0.47))], fill=(90, 220, 200))

    nfft, hop = 1024, 512
    frames = 1 + (len(x) - nfft) // hop
    win = np.hanning(nfft)
    idx = np.arange(nfft)[None, :] + hop * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * win, axis=1)).T          # (bins, frames)
    spec = np.clip((20 * np.log10(spec + 1e-6) + 32) / 72.0, 0, 1)

    rows = 260
    freqs = np.fft.rfftfreq(nfft, 1.0 / A.SR)
    edges = np.geomspace(45.0, 15000.0, rows + 1)               # log frequency axis
    small = np.empty((rows, frames), dtype=np.float32)
    for r in range(rows):
        sel = (freqs >= edges[r]) & (freqs < edges[r + 1])
        if not sel.any():
            sel = np.zeros_like(freqs, dtype=bool)
            sel[np.argmin(np.abs(freqs - edges[r]))] = True
        small[r] = spec[sel].mean(axis=0)
    small = small[::-1]

    stops = np.array([[8, 10, 26], [48, 24, 92], [140, 32, 110],
                      [230, 92, 70], [252, 214, 122]], dtype=np.float32)
    pos = small * (len(stops) - 1)
    li = np.clip(np.floor(pos).astype(int), 0, len(stops) - 2)
    frac = (pos - li)[..., None]
    rgb = stops[li] * (1 - frac) + stops[li + 1] * frac

    img.paste(Image.fromarray(rgb.astype(np.uint8), "RGB").resize((W, HS), Image.BILINEAR),
              (0, HW + 22))
    d.text((6, HW + 4), "waveform + spectrogram (45 Hz - 15 kHz, log)  ·  48 kHz mono",
           fill=(175, 190, 215))
    d.text((6, 4), "voice-over  ·  music bed  ·  sfx", fill=(150, 165, 195))
    img.save(path)
    return path


def main():
    mix = None
    if os.path.exists(MP4):
        mix = check_mp4()
    if os.path.exists(AVI):
        info, x, pcm = check_avi()
        if mix is None:
            mix = x
    wav_mix = check_wav()
    if mix is None:
        mix = wav_mix
    check_voice(mix)
    print("SPECTROGRAM")
    p = audio_png(mix, os.path.join(OUT, "audio.png"))
    check(os.path.getsize(p) > 5000, "wrote %s (%d bytes)"
          % (os.path.basename(p), os.path.getsize(p)))
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

