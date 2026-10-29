#!/usr/bin/env python3
"""
Minimal AVI writer with one MJPEG video stream and one PCM audio stream.

MJPEG ('MJPG') + 16-bit PCM in AVI is the most widely playable pairing that
can be produced without a codec library: every frame is a JPEG, and the audio
is raw samples, so VLC / mpv / ffmpeg / QuickTime all open the file directly.
"""

import struct

AUDIO_STREAM_ID = b"01wb"
VIDEO_STREAM_ID = b"00db"


def _chunk(cid, data):
    out = cid + struct.pack("<I", len(data)) + data
    if len(data) & 1:
        out += b"\x00"
    return out


def _list(kind, payload):
    body = kind + payload
    return b"LIST" + struct.pack("<I", len(body)) + body


def write_avi_mjpeg(path, jpeg_frames, width, height, fps, pcm, sample_rate):
    """pcm: interleaved little-endian 16-bit mono samples (bytes)"""
    n = len(jpeg_frames)
    spf = sample_rate // fps                    # samples per video frame
    if spf * fps != sample_rate:
        raise ValueError("sample_rate must be a multiple of fps")
    block_align = 2
    if len(pcm) != n * spf * block_align:
        raise ValueError("pcm length %d != %d frames * %d samples * 2 bytes"
                         % (len(pcm), n, spf))

    avih = struct.pack("<IIIIIIIIII4I",
                       int(1000000 / fps),
                       max(len(f) for f in jpeg_frames) * fps,
                       0,
                       0x10,                     # AVIF_HASINDEX
                       n, 0,
                       2,                        # dwStreams
                       max(len(f) for f in jpeg_frames),
                       width, height, 0, 0, 0, 0)

    v_strh = struct.pack("<4s4sIHHIIIIIIIIhhhh",
                         b"vids", b"MJPG", 0, 0, 0, 0,
                         1, fps, 0, n,
                         max(len(f) for f in jpeg_frames),
                         0xFFFFFFFF, 0,
                         0, 0, width, height)
    v_strf = struct.pack("<IiiHHIIiiII",
                         40, width, height, 1, 24,
                         struct.unpack("<I", b"MJPG")[0],   # biCompression
                         width * height * 3, 0, 0, 0, 0)

    a_strh = struct.pack("<4s4sIHHIIIIIIIIhhhh",
                         b"auds", b"\x00\x00\x00\x00", 0, 0, 0, 0,
                         1, sample_rate, 0, n * spf,
                         spf * block_align, 0xFFFFFFFF, block_align,
                         0, 0, 0, 0)
    a_strf = struct.pack("<HHIIHH",
                         1,                       # WAVE_FORMAT_PCM
                         1,                       # mono
                         sample_rate,
                         sample_rate * block_align,
                         block_align,
                         16)

    hdrl = _list(b"hdrl",
                 _chunk(b"avih", avih) +
                 _list(b"strl", _chunk(b"strh", v_strh) + _chunk(b"strf", v_strf)) +
                 _list(b"strl", _chunk(b"strh", a_strh) + _chunk(b"strf", a_strf)))

    movi = bytearray()
    index = bytearray()
    for i, jpg in enumerate(jpeg_frames):
        pos = 4 + len(movi)                      # offset from the 'movi' FourCC
        movi += _chunk(VIDEO_STREAM_ID, jpg)
        index += VIDEO_STREAM_ID + struct.pack("<III", 0x10, pos, len(jpg))

        aslice = pcm[i * spf * block_align:(i + 1) * spf * block_align]
        pos = 4 + len(movi)
        movi += _chunk(AUDIO_STREAM_ID, aslice)
        index += AUDIO_STREAM_ID + struct.pack("<III", 0x00, pos, len(aslice))

    body = (b"AVI " + hdrl + _list(b"movi", bytes(movi)) +
            _chunk(b"idx1", bytes(index)))
    blob = b"RIFF" + struct.pack("<I", len(body)) + body
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)
