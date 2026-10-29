# A video made with code

Two independent builds live here.

| # | file | what it is | deps |
|---|------|-----------|------|
| 1 | `explainer.py` | 26 s narrated explainer: motion design, Bangla voice-over, music bed + sound design, muxed into one AVI | pillow, numpy, miniaudio |
| 2 | `make_video.py` | 2 s animation + GIF/PNG, containers written from scratch | none (stdlib only) |

```
pip3 install -r requirements.txt
python3 explainer.py          # -> out/explainer.avi (+ .wav, contact.png)
python3 verify_explainer.py   # independent checks + out/audio.png

python3 make_video.py         # -> out/demo.avi, demo.gif, poster.png
python3 verify_video.py
```

## 1. The narrated explainer

`out/explainer.avi` — **640x360, 24 fps, 625 frames (26.0 s), MJPEG video +
48 kHz 16-bit mono PCM audio in a single RIFF/AVI file, 11.6 MB.**

* `out/explainer.wav` — the mix on its own (bit-identical to the AVI audio track)
* `out/contact.png` — one poster frame per scene
* `out/audio.png` — waveform + log-frequency spectrogram of the mix

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
rounded to a whole number of frames. That is why the video is 26 s and not 25 s.

### How the picture is made

* everything is drawn with Pillow at **2x (1280x720)** and downsampled with
  LANCZOS, so edges and text are clean
* keyframes everywhere: `ease_out`, `ease_in_out`, `ease_out_back` (cards,
  chips, nodes) and `ease_out_expo` (number counters)
* per scene: gradient + glow beds, film-strip perforations, staggered card
  reveals, animated dashed pipeline with travelling pulses, count-up stats with
  a live level meter, logo with an expanding ring pulse
* continuous motion: slow 3.5 % push-in on every scene, drifting glows, floating
  cards, scrolling perforations
* transitions: 0.36 s diagonal wipe with a soft edge, blended over two rendered
  frames; global fade-in from black and fade-out to black
* post: vignette + animated film grain

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
* **mix**: the music is side-chain ducked by the voice envelope (−0.72 depth), so
  speech always sits on top; soft-clip, fades, normalise to −0.7 dBFS peak

### Container (`avilib.py`)

`write_avi_mjpeg()` writes both streams by hand: `avih` (2 streams), two `strl`
blocks (`vids`/`MJPG` + `auds`/PCM `WAVEFORMATEX`), `movi` with `00db`/`01wb`
chunks interleaved one video frame = 2000 audio samples, and an `idx1` index.
MJPEG + PCM is the most compatible pairing that needs no codec library, so VLC,
mpv, ffmpeg and QuickTime all open the file as-is.

### Verification

`verify_explainer.py` re-parses the finished AVI instead of trusting the writer:

```
$ python3 verify_explainer.py
AVI
  ok   AVI: RIFF....AVI signature
  ok   AVI: RIFF size 12132942 == filesize-8 (12132942)
  ok   AVI: two streams, ['vids', 'auds']
  ok   AVI: video handler is MJPG
  ok   AVI: strf biCompression == MJPG
  ok   AVI: 640x360 video
  ok   AVI: 24 fps
  ok   AVI: strh length 625 == 625 chunks in movi
  ok   AVI: audio is 16-bit mono PCM
  ok   AVI: audio is 48000 Hz
  ok   AVI: PCM block align / byte rate consistent
  ok   AVI: 625 video + 625 audio chunks, 1250 index entries
  ok   AVI: index is interleaved video/audio
  ok   AVI: idx1 offsets resolve to real chunks
        frame  78  (640, 360)  mean  38.7  std 36.6
        frame 156  (640, 360)  mean  27.2  std 20.8
        frame 312  (640, 360)  mean  27.4  std 19.3
        frame 468  (640, 360)  mean  30.1  std 32.7
        frame 546  (640, 360)  mean  30.6  std 33.2
  ok   AVI: frames decode out of the container (size/brightness/contrast)
  ok   AVI: fade in / fade out (first mean 10.7, last mean 1.0)
  ok   AVI: 2500000 audio bytes == 625 frames x 2000 samples x 2 bytes
  ok   AVI: every audio chunk holds exactly 2000 samples
  ok   AVI: no clipped samples (peak 0.920)
  ok   AVI: healthy level (rms 0.216)
  ok   AVI: audio 26.042 s == video 26.042 s (A/V in sync)
WAV
  ok   WAV: mono, 16-bit, 48000 Hz
  ok   WAV: same byte length as the AVI audio track
  ok   WAV: bit-identical samples to the AVI audio
VOICE
  ok   speech present in 'intro   ' at  0.50 s (rms 0.224)
  ok   speech present in 'problem ' at  5.08 s (rms 0.225)
  ok   speech present in 'solution' at 11.00 s (rms 0.225)
  ok   speech present in 'stats   ' at 16.79 s (rms 0.214)
  ok   speech present in 'outro   ' at 23.54 s (rms 0.240)
  ok   music continues (ducked) between lines (rms 0.111)
SPECTROGRAM
  ok   wrote audio.png (209619 bytes)

all checks passed
```

The frames are also compared pixel-by-pixel against a fresh render
(`mean|diff| ≈ 0.4–2.1`, i.e. JPEG quantisation only), which proves the file's
frame order matches its timeline.

### Customising

```python
SCRIPT = (("intro", "…", 4.2), …)   # scene key, Bangla line, minimum length
ACCENTS = ((0, 1.50, lambda: A.blip(1180.0, amp=0.30)), …)   # sfx per reveal
VW, VH, FPS = 640, 360, 24
python3 explainer.py --quality 90   # bigger JPEGs, better gradients
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

* No ffmpeg here, so both files use formats that need no codec library:
  uncompressed BGR (demo) and MJPEG (explainer) video, plus raw PCM audio.
  That is why they are megabytes instead of kilobytes.
* With ffmpeg on the machine, converting is one command:

  ```
  ffmpeg -i out/explainer.avi -c:v libx264 -crf 20 -c:a aac -b:a 128k out/explainer.mp4
  ```

* The voice-over comes from Google Translate TTS and is fetched **once**, then
  cached as WAV in `assets/voice/`. Delete those files to re-voice a line, or
  re-record them yourself and keep the filenames (`vo_intro.wav`, ...).
* Audio is mono 48 kHz by design: it keeps the AVI interleave trivially exact
  (2000 samples per frame at 24 fps) and the file small.
* Bengali text is shaped by Pillow/raqm through Noto Sans Bengali. Latin text
  must not be drawn with the Bengali font (it has no Latin glyphs), so every
  mixed line is split into a Bangla run and a mono run.
