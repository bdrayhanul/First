#!/usr/bin/env python3
"""
Sound design for the explainer: a procedural music bed, SFX and voice-over
assembly, all in numpy (16-bit PCM out, 48 kHz mono).

Everything is synthesised from oscillators, noise and envelopes -- there are
no samples on disk. Only the narration comes from outside (a TTS request that
is cached as WAV under assets/voice/).
"""

import os
import subprocess
import urllib.parse
import wave

import miniaudio
import numpy as np

SR = 48000


# ------------------------------------------------------------------ basics --

def nsamples(dur):
    return int(round(dur * SR))


def t_axis(dur):
    return np.arange(nsamples(dur), dtype=np.float64) / SR


def sine(freq, dur, amp=1.0, phase=0.0):
    t = t_axis(dur)
    if callable(freq):                      # frequency sweep
        ph = 2 * np.pi * np.cumsum(freq(t)) / SR
        return amp * np.sin(ph + phase)
    return amp * np.sin(2 * np.pi * freq * t + phase)


def triangle(freq, dur, amp=1.0):
    t = t_axis(dur)
    ph = (t * freq) % 1.0
    return amp * (4.0 * np.abs(ph - 0.5) - 1.0)


def noise(dur, seed=0):
    return np.random.default_rng(seed).standard_normal(nsamples(dur)) * 0.5


def env_adsr(dur, a=0.01, d=0.1, s=0.7, r=0.3):
    n = nsamples(dur)
    a_n, d_n, r_n = nsamples(a), nsamples(d), nsamples(r)
    s_n = max(0, n - a_n - d_n - r_n)
    parts = [np.linspace(0, 1, a_n, endpoint=False) if a_n else np.array([]),
             np.linspace(1, s, d_n, endpoint=False) if d_n else np.array([]),
             np.full(s_n, s),
             np.linspace(s, 0, r_n) if r_n else np.array([])]
    e = np.concatenate(parts)
    if len(e) < n:
        e = np.pad(e, (0, n - len(e)))
    return e[:n]


def exp_env(dur, tau=0.2):
    return np.exp(-t_axis(dur) / max(1e-4, tau))


def hit_env(dur, attack=0.004, tau=0.2):
    e = exp_env(dur, tau)
    a_n = max(1, nsamples(attack))
    e[:a_n] *= np.linspace(0, 1, a_n)
    return e


# ------------------------------------------------------------------ filters --

def _fft_shape(x, gain_fn):
    n = len(x)
    nfft = 1 << (n + 4096 - 1).bit_length()
    spec = np.fft.rfft(x, nfft)
    freqs = np.fft.rfftfreq(nfft, 1.0 / SR)
    return np.fft.irfft(spec * gain_fn(freqs), nfft)[:n]


def lowpass(x, cutoff, order=2):
    return _fft_shape(x, lambda f: 1.0 / np.sqrt(1.0 + (f / cutoff) ** (2 * order)))


def highpass(x, cutoff, order=2):
    return _fft_shape(x, lambda f: 1.0 / np.sqrt(1.0 + (cutoff / np.maximum(f, 1e-6)) ** (2 * order)))


def bandpass(x, lo, hi, order=2):
    return _fft_shape(x, lambda f: 1.0 / np.sqrt(
        (1.0 + (f / hi) ** (2 * order)) * (1.0 + (lo / np.maximum(f, 1e-6)) ** (2 * order))))


def reverb(x, dur=1.6, mix=0.25, tone=4500.0, seed=3):
    """exponentially decaying noise impulse response, applied by FFT"""
    n = nsamples(dur)
    ir = np.random.default_rng(seed).standard_normal(n) * np.exp(-np.arange(n) / (0.32 * SR))
    ir = lowpass(ir, tone)
    ir[:nsamples(0.012)] *= np.linspace(0, 1, nsamples(0.012))
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    y = fft_convolve(x, ir)[:len(x)]
    return (1 - mix) * x + mix * y * 1.6


def fft_convolve(a, b):
    n = len(a) + len(b) - 1
    nfft = 1 << (n - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(a, nfft) * np.fft.rfft(b, nfft), nfft)
    return y[:n]


# ------------------------------------------------------------------ mixing --

def place(dst, src, at):
    """add `src` into `dst` starting at `at` seconds (clipped to the buffer)"""
    i = int(round(at * SR))
    if i >= len(dst):
        return
    if i < 0:
        src = src[-i:]
        i = 0
    n = min(len(src), len(dst) - i)
    dst[i:i + n] += src[:n]


def smooth(x, attack=0.02, release=0.25):
    """one-pole envelope follower (numeric, vectorised per block)"""
    out = np.empty_like(x)
    a_att = 1.0 - np.exp(-1.0 / (attack * SR))
    a_rel = 1.0 - np.exp(-1.0 / (release * SR))
    v = 0.0
    for i in range(len(x)):
        target = abs(x[i])
        a = a_att if target > v else a_rel
        v += a * (target - v)
        out[i] = v
    return out


def normalize(x, peak=0.9):
    m = float(np.max(np.abs(x))) or 1.0
    return x * (peak / m)


def soft_clip(x, drive=1.0):
    return np.tanh(x * drive) / np.tanh(drive)


# ------------------------------------------------------------------- music --

def hz(midi):
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


# A minor 9 -> Fmaj7 -> Cmaj9 -> G6, one bar each (120 bpm, 4/4 = 2 s per bar)
PROGRESSION = (
    (45, (57, 60, 64, 71)),      # Am9
    (41, (53, 57, 60, 64)),      # Fmaj7
    (48, (55, 60, 64, 74)),      # Cmaj9
    (43, (55, 59, 62, 64)),      # G6
)


def pad_voice(midi, dur, amp=0.16, detune=0.0015):
    a = sine(hz(midi), dur, amp)
    b = sine(hz(midi) * (1 + detune), dur, amp, phase=1.1)
    c = sine(hz(midi) * (1 - detune), dur, amp * 0.8, phase=2.3)
    return (a + b + c) * env_adsr(dur, a=0.45, d=0.35, s=0.72, r=1.1)


def pluck(midi, dur, amp=0.12, tau=0.22):
    f = hz(midi)
    x = triangle(f, dur, amp) * 0.7 + sine(f * 2.0, dur, amp * 0.3)
    return x * hit_env(dur, attack=0.003, tau=tau)


def kick(dur=0.42, amp=0.5):
    return sine(lambda t: 48 + 130 * np.exp(-t / 0.035), dur, amp) * hit_env(dur, 0.002, 0.10)


def hat(dur=0.07, amp=0.10):
    return highpass(noise(dur, seed=7), 7000.0) * hit_env(dur, 0.001, 0.02) * amp


def build_music(duration, bpm=120.0, seed=11):
    """pad + arpeggio + bass + soft kit, locked to a 2 s bar grid"""
    n = nsamples(duration)
    kit = np.zeros(n)
    pad_bus = np.zeros(n)
    arp_bus = np.zeros(n)
    low_bus = np.zeros(n)
    bar = 240.0 / bpm

    for b in range(int(np.ceil(duration / bar))):
        root, notes = PROGRESSION[b % len(PROGRESSION)]
        t0 = b * bar

        for m in notes:
            place(pad_bus, pad_voice(m, bar + 1.1), t0)

        place(low_bus, sine(hz(root - 12), bar * 0.9, 0.20) *
              env_adsr(bar * 0.9, 0.01, 0.4, 0.55, 0.3), t0)
        place(low_bus, sine(hz(root - 5), bar * 0.35, 0.12) *
              hit_env(bar * 0.35, 0.01, 0.12), t0 + bar * 0.75)

        for k in range(8):                       # 8th-note arpeggio
            m = notes[k % len(notes)] + (12 if k >= len(notes) else 0)
            place(arp_bus, pluck(m, 0.5, amp=0.10 - 0.004 * (k % 3)), t0 + k * bar / 8)

        for beat in (0, 2):
            place(kit, kick(amp=0.42), t0 + beat * bar / 4)
        for k in range(4):
            place(kit, hat(amp=0.05), t0 + k * bar / 4)
            place(kit, hat(), t0 + (k + 0.5) * bar / 4)

    pad_bus = reverb(lowpass(pad_bus, 2600.0), dur=2.2, mix=0.32, tone=3800.0, seed=seed)
    arp_bus = reverb(arp_bus, dur=1.1, mix=0.18, tone=6000.0, seed=seed + 1)
    return kit + pad_bus * 0.55 + arp_bus * 0.8 + low_bus


# --------------------------------------------------------------------- sfx --

def sweep_noise(dur, f0, f1, q=1.2, seed=5, chunks=24):
    """band-limited noise with a gliding centre frequency: the whoosh engine"""
    x = noise(dur, seed)
    n = len(x)
    win = max(64, 3 * n // chunks)
    acc = np.zeros(n)
    wsum = np.zeros(n)
    taper = np.hanning(win)
    for c in range(chunks):
        f = f0 * (f1 / f0) ** (c / max(1, chunks - 1))
        seg = bandpass(x, f / q, f * q)
        start = int(c * (n - win) / max(1, chunks - 1))
        acc[start:start + win] += seg[start:start + win] * taper
        wsum[start:start + win] += taper
    return acc / np.maximum(wsum, 1e-6)


def whoosh(dur=0.55, seed=5):
    body = sweep_noise(dur, 400.0, 5200.0, q=1.5, seed=seed)
    body *= env_adsr(dur, a=0.22, d=0.12, s=0.5, r=0.2)
    air = highpass(noise(dur, seed + 1), 3500.0) * hit_env(dur, 0.05, 0.16) * 0.25
    return body * 0.55 + air


def riser(dur=1.2, seed=9):
    ramp = np.linspace(0, 1, nsamples(dur)) ** 2.2
    hiss = sweep_noise(dur, 700.0, 9000.0, q=1.1, seed=seed) * ramp
    tone = sine(lambda t: 180 + 720 * (t / dur) ** 1.6, dur, 0.10) * ramp
    return hiss * 0.35 + tone


def blip(freq=1320.0, dur=0.16, amp=0.5):
    x = (sine(freq, dur) * exp_env(dur, 0.045) +
         sine(freq * 1.5, dur, 0.5) * exp_env(dur, 0.03) +
         sine(freq * 0.5, dur, 0.35) * exp_env(dur, 0.07))
    click = highpass(noise(dur, 21), 6000.0) * hit_env(dur, 0.001, 0.006) * 0.15
    return (x + click) * amp


def tick(dur=0.045, amp=0.20):
    return highpass(noise(dur, 33), 8000.0) * hit_env(dur, 0.001, 0.012) * amp


def thud(dur=0.35, amp=0.35):
    return sine(lambda t: 42 + 60 * np.exp(-t / 0.06), dur, amp) * hit_env(dur, 0.003, 0.09)


def chime(dur=1.8, root=523.25, amp=0.4):
    x = np.zeros(nsamples(dur))
    for k, (mult, gain, tau) in enumerate(((1.0, 1.0, 0.55), (2.0, 0.45, 0.42),
                                           (3.0, 0.22, 0.30), (4.2, 0.12, 0.22))):
        place(x, sine(root * mult, dur, gain) * exp_env(dur, tau), k * 0.012)
    return reverb(x, dur=1.4, mix=0.35, tone=7000.0) * amp


# ------------------------------------------------------------------- voice --

def write_wav(path, x, sr=SR):
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return path


def read_wav(path, sr=SR):
    with wave.open(path, "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (sr, 1, 2):
            raise ValueError("%s is not %d Hz mono 16-bit" % (path, sr))
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0


def narrate(text, name, cache_dir, lang="bn", sr=SR):
    """fetch (once, cached as WAV) and return TTS speech as 48 kHz mono float"""
    path = os.path.join(cache_dir, name + ".wav")
    if not os.path.exists(path):
        os.makedirs(cache_dir, exist_ok=True)
        mp3 = os.path.join(cache_dir, name + ".mp3")
        url = ("https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob"
               "&tl=%s&q=%s" % (lang, urllib.parse.quote(text)))
        subprocess.run(["curl", "-sS", "--retry", "2", "--max-time", "30",
                        "-A", "Mozilla/5.0", "-o", mp3, url], check=True)
        dec = miniaudio.decode_file(mp3, output_format=miniaudio.SampleFormat.SIGNED16,
                                    nchannels=1, sample_rate=sr)
        x = np.frombuffer(bytes(dec.samples), dtype=np.int16).astype(np.float64) / 32768.0
        os.remove(mp3)
        write_wav(path, x, sr)
    else:
        x = read_wav(path, sr)

    x = highpass(x, 95.0)
    # gentle levelling: pull down plosive peaks, then lift the body
    peak_env = np.maximum(smooth(np.abs(x), 0.005, 0.12), 1e-3)
    x = x / (1.0 + peak_env * 4.0)
    return normalize(x, 0.72)


def duck(music, voice, depth=0.55, attack=0.06, release=0.35):
    """side-chain style gain dip on the music, driven by the voice envelope"""
    if not np.any(voice):
        return music
    e = smooth(np.abs(voice), attack, release)
    e = e / (float(np.max(e)) or 1.0)
    return music * (1.0 - depth * np.clip(e, 0.0, 1.0))
