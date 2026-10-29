# A video made only with code

`make_video.py` renders a 2-second animation and writes three files **using
nothing but the Python standard library** — no ffmpeg, no Pillow, no numpy.
The AVI, GIF and PNG containers, the GIF LZW compressor, the 5x7 bitmap font
and the drawing primitives are all implemented in the script.

```
python3 make_video.py      # -> out/demo.avi, out/demo.gif, out/poster.png
python3 verify_video.py    # re-parses the files and checks every frame
```

## What it produces

| file | container | video | size |
|------|-----------|-------|------|
| `out/demo.avi` | RIFF/AVI, `vids`/`DIB `, `BI_RGB` 24-bit, bottom-up BGR, `idx1` index | 384x216, 30 fps, 60 frames | ~14 MB |
| `out/demo.gif` | GIF89a, 256-colour global table, NETSCAPE2.0 loop, hand-rolled LZW | 320x180, 15 fps, 30 frames | ~90 KB |
| `out/poster.png` | PNG, zlib deflate, 8-bit truecolour | frame 30, 384x216 | ~3 KB |

## How it works

* `Canvas` is a flat `bytearray` of RGB triples with `rect`, `disc`, `ring`,
  `vgrad` and `text` primitives.
* `FONT` is a 5x7 bitmap font written as one 7-row string per glyph.
* `render(cv, i, n)` draws one frame from scratch; all coordinates come from
  the canvas size, so the same code renders 384x216 and 320x180 natively.
* `write_avi` builds `avih`, `strh`, `strf`, the `movi` list and the `idx1`
  index by hand, flipping rows and swapping R/B for AVI's bottom-up BGR.
* `lzw_encode` is a GIF-flavoured LZW: it emits a CLEAR code as soon as the
  next free code would reach 512, so every code stays 9 bits wide.

## Verification

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

## If you want an MP4

The AVI is uncompressed, so any converter will read it. On a machine with
ffmpeg installed:

```
ffmpeg -i out/demo.avi -c:v libx264 -pix_fmt yuv420p out/demo.mp4
```

## Customising

Edit the constants at the top of `make_video.py`:

```python
W, H, FPS, FRAMES = 384, 216, 30, 60   # AVI size / frame rate / length
GW, GH = 320, 180                      # GIF size
TITLE    = "CODE MAKES VIDEO"
SUBTITLE = "PURE PYTHON - NO FFMPEG"
```
