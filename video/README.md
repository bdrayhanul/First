# A video made with code

Two independent builds live here.

| # | file | what it is | deps |
|---|------|-----------|------|
| 1 | `explainer.py` | 26 s narrated explainer: motion design, Bangla voice-over, music bed + sound design, encoded to MP4 | pillow, numpy, miniaudio, imageio-ffmpeg |
| 2 | `make_video.py` | 2 s animation + GIF/PNG, containers written from scratch | none (stdlib only) |

```
pip3 install -r requirements.txt
python3 explainer.py          # -> out/explainer.mp4 (+ .wav, contact.png)
python3 verify_explainer.py   # independent checks + out/audio.png

python3 make_video.py         # -> out/demo.avi, demo.gif, poster.png
python3 verify_video.py
```

## 1. The narrated explainer

`out/explainer.mp4` — **1280x720, 24 fps, 625 frames (26.0 s), H.264 High
(CRF 16, yuv420p) + AAC 160 kb/s 48 kHz mono, 3.5 MB, faststart.**

* `out/explainer.wav` — the mix on its own, before AAC
* `out/contact.png` — one poster frame per scene
* `out/audio.png` — waveform + log-frequency spectrogram of the mix

If `ffmpeg` is not available the same script falls back to an uncompressed
MJPEG + PCM AVI (`python3 explainer.py --avi`), which needs no encoder — that
path is what the repo used before `imageio-ffmpeg` was added, and it is why the
fallback looks softer: MJPEG at the same bitrate is far weaker than x264.

### Timeline

| scene | in | length | narration (bn) |
|---|---|---|---|
| intro | 0.0 s | 4.58 s | কোড দিয়েই পুরো একটা ভিডিও বানানো যায়। |
| problem | 4.58 s | 5.92 s | এখানে কোনো ভিডিও এনকোডার নেই, সাউন্ড লাইব্রেরিও নেই। |
| solution | 10.50 s | 5.79 s | তাই নিজেই লিখলাম এনকোডার, কনটেইনার আর সাউন্ড। |
| stats | 16.29 s | 6.75 s | ছশো ফ্রেম, চব্বিশ এফপিএস, আটচল্লিশ কিলোহার্টজ অডিও। |
| outro | 23.04 s | 3.00 s | ধন্যবাদ। |

Scene lengths are **derived from the narration**, not hard-coded: the TTS clip is
fetched, measured, and the scene is set to `max(min_dur, voice + 0.95 s)`, then
rounded to a whole number of frames.

### How the picture is made

* drawn with Pillow at **3x (1920x1080)** in 640x360 design units, then
  downsampled to 1280x720 with LANCZOS — that supersampling is the real
  anti-aliasing, and it is why text edges stay clean
* keyframes everywhere: `ease_out`, `ease_in_out`, `ease_out_back` (cards,
  chips, nodes) and `ease_out_expo` (number counters)
* per scene: gradient + glow beds, film-strip perforations, staggered card
  reveals, animated dashed pipeline with travelling pulses, count-up stats with
  a live level meter, logo with an expanding ring pulse
* continuous motion: slow 2 % push-in on every scene, drifting glows, floating
  cards, scrolling perforations
* transitions: 0.36 s diagonal wipe with a soft edge, blended over two rendered
  frames; global fade-in from black and fade-out to black
* post: vignette + a very light grain (1.8 %) — heavier grain was measured to
  cost most of the bitrate for nothing

### How the sound is made (`audio_synth.py`)

No samples on disk — everything is synthesised with numpy at 48 kHz:

* **music bed**: Am9 → Fmaj7 → Cmaj9 → G6, one 2 s bar each; detuned 3-osc pads
  with ADSR, 8th-note triangle arpeggio, sine bass, soft kick and hats; FFT
  low-pass and a convolution reverb built from decaying noise
* **sound design**: riser under the title, a whoosh before every scene change,
  a low thud on each cut, blips on every card/chip/node/number reveal, ticks on
  the meter, a bell chime on the outro; whooshes come from band-limited noise
  with a gliding centre frequency (overlap-add of 24 bandpassed chunks)
* **voice-over**: fetched once from Google Translate TTS (`tl=bn`), resampled to
  48 kHz, high-passed at 95 Hz, levelled, cached as `assets/voice/vo_*.wav`
* **mix**: the music is side-chain ducked by the voice envelope, so speech always
  sits on top; soft-clip, fades, normalise to −0.7 dBFS peak


### Container (`avilib.py`, the fallback path)

`write_avi_mjpeg()` writes both streams by hand: `avih` (2 streams), two `strl`
blocks (`vids`/`MJPG` + `auds`/PCM `WAVEFORMATEX`), `movi` with `00db`/`01wb`
chunks interleaved one video frame = 2000 audio samples, and an `idx1` index.
MJPEG + PCM is the most compatible pairing that needs no codec library, so VLC,
mpv, ffmpeg and QuickTime all open the file as-is.

### Verification

`verify_explainer.py` does not trust the encode. It asks ffmpeg for the stream
layout, decodes frames *back out of the MP4*, re-renders the same timestamps and
measures PSNR, then decodes the AAC track and correlates it with the mix:

```
$ python3 verify_explainer.py
MP4
  ok   MP4: H.264 video stream
  ok   MP4: 1280x720 video
  ok   MP4: 24 fps
  ok   MP4: yuv420p (plays everywhere)
  ok   MP4: AAC 48000 Hz mono audio
  ok   MP4: duration 26.040 s == 26.042 s of frames (A/V in sync)
        frame  78  1280x720  PSNR 41.04 dB  mean|err| 1.35
        frame 312  1280x720  PSNR 42.64 dB  mean|err| 1.29
        frame 546  1280x720  PSNR 41.56 dB  mean|err| 1.55
  ok   MP4: every sampled frame is >= 36 dB PSNR vs the render
  ok   MP4: decoded AAC matches the mix (correlation 0.99987)
  ok   MP4: audio track length 26.048 s vs mix 26.042 s
  ok   MP4: AAC level preserved (0.198 vs 0.198)
WAV
  ok   WAV: mono, 16-bit, 48000 Hz
  ok   WAV: 26.042 s long, matches the timeline
VOICE
  ok   speech present in 'intro   ' at  0.50 s (rms 0.203)
  ok   speech present in 'problem ' at  5.08 s (rms 0.221)
  ok   speech present in 'solution' at 11.00 s (rms 0.220)
  ok   speech present in 'stats   ' at 16.79 s (rms 0.214)
  ok   speech present in 'outro   ' at 23.54 s (rms 0.240)
  ok   music continues (ducked) between lines (rms 0.111)
SPECTROGRAM
  ok   wrote audio.png (209619 bytes)

all checks passed
```

`--avi` switches the verifier over to the RIFF checks (two streams, `movi`
chunks, `idx1` offsets, PCM reassembly) when the fallback file is built instead.

### Why the first encode looked soft (and what changed)

The first version was a 640x360 MJPEG AVI averaging 15 KB per frame. Measured
problems, in order of impact:

| cause | fix |
|---|---|
| ~3.4 Mbit/s budget for 720p-equivalent detail — x264 needs ~900 kb/s for this content | H.264 CRF 16 via `imageio-ffmpeg` (3.5 MB total instead of 11.6 MB at 4x the pixels) |
| animated film grain at 5 % — high-frequency noise eats the bitrate first, so text got starved | grain reduced to 1.8 %, vignette kept |
| 4:2:2 chroma subsampling smeared coloured text | x264 `yuv420p` with `-tune animation`, and coloured text now sits on flat backgrounds |
| only 2x supersampling | 3x (1920x1080) then LANCZOS to 720p |
| push-in resampled the finished 720p image | 2 % push-in with BICUBIC |

Result: 41-43 dB PSNR against the reference render, i.e. the encode is
visually transparent.

### Customising

```python
SCRIPT = (("intro", "…", 4.2), …)   # scene key, Bangla line, minimum length
ACCENTS = ((0, 1.50, lambda: A.blip(1180.0, amp=0.30)), …)   # sfx per reveal
VW, VH, SS, OW, OH, FPS = 640, 360, 3, 1280, 720, 24
```

```bash
python3 explainer.py --crf 12      # near-lossless, bigger file
python3 explainer.py --crf 22      # smaller file, more artefacts
python3 explainer.py --avi         # MJPEG/PCM fallback, no ffmpeg needed
```

## 2. The stdlib-only demo (`make_video.py`)


### What it produces

| file | container | video | size |
|------|-----------|-------|------|
| `out/demo.avi` | RIFF/AVI, `vids`/`DIB `, `BI_RGB` 24-bit, bottom-up BGR, `idx1` index | 384x216, 30 fps, 60 frames | ~14 MB |
| `out/demo.gif` | GIF89a, 256-colour global table, NETSCAPE2.0 loop, hand-rolled LZW | 320x180, 15 fps, 30 frames | ~90 KB |
| `out/poster.png` | PNG, zlib deflate, 8-bit truecolour | frame 30, 384x216 | ~3 KB |

### How it works

* `Canvas` is a flat `bytearray` of RGB triples with `rect`, `disc`, `ring`,
  `vgrad` and `text` primitives.
* `FONT` is a 5x7 bitmap font written as one 7-row string per glyph.
* `render(cv, i, n)` draws one frame from scratch; all coordinates come from
  the canvas size, so the same code renders 384x216 and 320x180 natively.
* `write_avi` builds `avih`, `strh`, `strf`, the `movi` list and the `idx1`
  index by hand, flipping rows and swapping R/B for AVI's bottom-up BGR.
* `lzw_encode` is a GIF-flavoured LZW: it emits a CLEAR code as soon as the
  next free code would reach 512, so every code stays 9 bits wide.

### Verification

`verify_video.py` does not trust the writers. It re-parses the RIFF chunk
tree, walks the GIF block stream, decodes the LZW back to indices with a
separate decoder, and compares the result with a freshly rendered frame:

```
$ python3 verify_video.py
AVI
  ok   AVI: RIFF....AVI signature
  ok   AVI: RIFF size 14931584 == filesize-8 (14931584)
  ok   AVI: resolution 384x216
  ok   AVI: stream is vids/DIB
  ok   AVI: BI_RGB, 24 bit
  ok   AVI: 30 fps
  ok   AVI: avih total frames 60 / strh length 60
  ok   AVI: movi holds 60 frame chunks
  ok   AVI: idx1 holds 60 entries
  ok   AVI: every frame chunk is '00db'
  ok   AVI: every frame payload is 248832 bytes
  ok   AVI: idx1 offsets resolve to the frame chunks
  ok   AVI: frame 40 decodes to exactly the rendered pixels
GIF
  ok   GIF: signature b'GIF89a'
  ok   GIF: global colour table present
  ok   GIF: canvas is 320x180
  ok   GIF: 30 image frames
  ok   GIF: NETSCAPE2.0 looping extension
  ok   GIF: per-frame delay [6] (1/100 s)
  ok   GIF: LZW min code size 8
  ok   GIF: every frame covers the full canvas
  ok   GIF: all 30 frames decode back to the rendered pixels
  ok   GIF: 216-colour cube + 40-step gray ramp
PNG
  ok   PNG: signature
  ok   PNG: every chunk CRC32 is valid
  ok   PNG: 384x216
  ok   PNG: decompressed scanline bytes
  ok   PNG: pixels match rendered frame 30

all checks passed
```

### Customising

Edit the constants at the top of `make_video.py`:

```python
W, H, FPS, FRAMES = 384, 216, 30, 60   # AVI size / frame rate / length
GW, GH = 320, 180                      # GIF size
TITLE    = "CODE MAKES VIDEO"
SUBTITLE = "PURE PYTHON - NO FFMPEG"
```

## Notes and limits

* The explainer encodes with x264 through `imageio-ffmpeg`, which ships its own
  ffmpeg binary, so no system ffmpeg is needed. Without that wheel the `--avi`
  fallback writes MJPEG + raw PCM: it plays everywhere, but looks much softer at
  the same file size.
* The stdlib demo (`make_video.py`) still writes uncompressed BGR, because its
  whole point is doing it with no encoder at all.
* The voice-over comes from Google Translate TTS and is fetched **once**, then
  cached as WAV in `assets/voice/`. Delete those files to re-voice a line, or
  re-record them yourself and keep the filenames (`vo_intro.wav`, ...).
* Audio is mono 48 kHz: it keeps the AVI fallback's interleave exact (2000 samples
  per frame at 24 fps) and the AAC track small.
* Bengali text is shaped by Pillow/raqm through Noto Sans Bengali. Latin text
  must not be drawn with the Bengali font (it has no Latin glyphs), so every
  mixed line is split into a Bangla run and a mono run.
