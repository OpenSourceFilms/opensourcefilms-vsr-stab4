#!/usr/bin/env python3
"""Create three tiny synthetic 8-bit source / 16-bit enhanced PNG pairs (no footage)."""
import argparse
import json
import pathlib
import struct
import zlib


def png_rgb(path, w, h, frame, depth):
    channel_max = 256 if depth == 8 else 65536
    rows = []
    for y in range(h):
        row = bytearray(b"\x00")
        for x in range(w):
            values = [
                (x * 13 + y * 7 + frame * 29) % 256,
                (x * 5 + y * 17 + frame * 43) % 256,
                (x * 23 + y * 3 + frame * 37) % 256,
            ]
            if depth == 16:
                values = [(v * 257 + ((x + y + frame) % 5) * 9) % channel_max for v in values]
            for value in values:
                row.extend(value.to_bytes(depth // 8, "big"))
        rows.append(bytes(row))

    def chunk(kind, contents):
        return (struct.pack(">I", len(contents)) + kind + contents +
                struct.pack(">I", zlib.crc32(kind + contents) & 0xffffffff))
    data = (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"".join(rows))) +
            chunk(b"IEND", b""))
    with path.open("xb") as stream:
        stream.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("directory", type=pathlib.Path)
    args = ap.parse_args()
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    source = root / "source"
    enhanced = root / "enhanced"
    source.mkdir()
    enhanced.mkdir()
    for frame in range(3):
        png_rgb(source / ("f%04d.png" % frame), 16, 16, frame, 8)
        png_rgb(enhanced / ("f%04d.png" % frame), 32, 32, frame, 16)
    request = {
        "schema": "osf.vsr.stab4_request.v1",
        "shot_id": "synthetic-demo",
        "source_dir": str(source),
        "enhanced_dir": str(enhanced),
        "output_dir": str(root / "rendered"),
        "first_frame": 0, "frame_count": 3,
        "source_width": 16, "source_height": 16,
        "target_width": 32, "target_height": 32,
        "fps_num": 24, "fps_den": 1, "radius": 4,
    }
    (root / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    print(root / "request.json")


if __name__ == "__main__":
    main()
