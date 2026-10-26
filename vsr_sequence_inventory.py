#!/usr/bin/env python3
"""Read-only PNG frame-sequence inventory and deterministic input fingerprint.

Selected and adapted from OSF VSR source-inventory research. No inference,
storage service, model, decoding or proprietary media is required.

Fingerprint contract is deliberately the legacy OSF-VSR-SOURCE-SEQUENCE-v1:
SHA256 of a UTF-8/ASCII text record with a fixed header and ordered per-frame
(index, filename, full-file SHA256). No schema- or pixel-level quality claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

PNG_SIG = bytes.fromhex("89504e470d0a1a0a")
IDENTITY_SPEC = "OSF-VSR-SOURCE-SEQUENCE-v1"
# Deliberately limited to exactly one integer conversion and literal basename.
SAFE_PATTERN = re.compile(r"[A-Za-z0-9_.-]*%(?:0[1-9][0-9]{0,2})?d[A-Za-z0-9_.-]*\Z")
MAX_FRAMES = 100000


class InventoryError(ValueError):
    pass


def _positive_integer(v, field, limit):
    if type(v) is not int or not 0 < v <= limit:
        raise InventoryError(field + " must be a positive integer up to " + str(limit))
    return v


def _source(source):
    if not isinstance(source, dict):
        raise InventoryError("source must be a JSON object")
    if source.get("kind") != "sequence":
        raise InventoryError("only a sequence of PNG frames is supported")
    name = source.get("frame_pattern")
    if not isinstance(name, str) or ".." in name or not SAFE_PATTERN.fullmatch(name):
        raise InventoryError("frame_pattern must be one safe basename with one %d index")
    start = source.get("start_frame")
    if type(start) is not int or not 0 <= start <= 1000000000:
        raise InventoryError("start_frame must be a nonnegative integer")
    count = _positive_integer(source.get("frame_count"), "frame_count", MAX_FRAMES)
    if start + count > 1000000000:
        raise InventoryError("frame index range too large")
    width = _positive_integer(source.get("width"), "width", 100000)
    height = _positive_integer(source.get("height"), "height", 100000)
    depth = source.get("bit_depth")
    if type(depth) is not int or depth not in (8, 16):
        raise InventoryError("bit_depth must be 8 or 16")
    alpha = source.get("alpha")
    if alpha not in ("none", "straight", "premultiplied", "unknown"):
        raise InventoryError("alpha must be none, straight, premultiplied or unknown")
    raw_path = source.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise InventoryError("source path must be a nonempty string")
    folder = Path(raw_path)
    if folder.is_symlink() or not folder.is_dir():
        raise InventoryError("source directory missing or a symlink")
    return folder, name, start, count, width, height, depth, alpha


def frame_fingerprint(entries):
    """Compatible with the frozen original OSF VSR source-sequence v1 hash."""
    lines = [IDENTITY_SPEC + "\n"]
    for row in entries:
        idx = row["frame_index"]
        name = row["filename"]
        digest = row["sha256"]
        if type(idx) is not int or idx < 0:
            raise InventoryError("invalid frame_index")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise InventoryError("invalid fingerprint filename")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise InventoryError("invalid frame digest")
        lines.append(f"{idx}\t{name}\t{digest}\n")
    return hashlib.sha256("".join(lines).encode("ascii")).hexdigest()


def inventory(source):
    """Read each nominated PNG once; never modifies source or writes receipts."""
    folder, pattern, start, count, width, height, depth, alpha = _source(source)
    rows = []
    for index in range(start, start + count):
        filename = pattern % index
        path = folder / filename
        if path.is_symlink() or not path.is_file():
            raise InventoryError("missing or symlink frame: " + filename)
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            head = stream.read(26)
            if len(head) != 26 or head[:8] != PNG_SIG or head[12:16] != b"IHDR":
                raise InventoryError("invalid PNG signature/IHDR: " + filename)
            file_width, file_height = struct.unpack(">II", head[16:24])
            file_depth, colour = head[24], head[25]
            if (file_width, file_height, file_depth) != (width, height, depth):
                raise InventoryError("PNG geometry/depth mismatch: " + filename)
            if colour not in (2, 6):
                raise InventoryError("expected RGB or RGBA PNG: " + filename)
            if colour == 6 and alpha == "none":
                raise InventoryError("RGBA source incorrectly labelled alpha=none: " + filename)
            digest.update(head)
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
        def identity(s):
            return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
        if identity(before) != identity(after):
            raise InventoryError("frame changed while hashing: " + filename)
        rows.append({
            "frame_index": index, "filename": filename, "sha256": digest.hexdigest(),
            "size_bytes": after.st_size, "width": file_width, "height": file_height,
            "bit_depth": file_depth, "png_colour_type": colour,
        })
    return {
        "identity_spec": IDENTITY_SPEC,
        "source_path": str(folder),
        "start_frame": start,
        "frame_count": len(rows),
        "sequence_sha256": frame_fingerprint(rows),
        "total_hashed_bytes": sum(row["size_bytes"] for row in rows),
        "frames": rows,
        "exclusion_note": "Only the selected window is fingerprinted; other directory entries are excluded.",
        "does_not_validate_png_crc_or_pixels": True,
        "creative_approval": False,
        "production_write_allowed": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_json", help="Local JSON source descriptor, as documented")
    parser.add_argument("--receipt", help="Optional new receipt file (create-only); omit to print only")
    args = parser.parse_args(argv)
    try:
        raw = Path(args.source_json).read_text(encoding="utf-8")
        source = json.loads(raw)
        result = inventory(source)
        if args.receipt:
            target = Path(args.receipt)
            # A receipt must not be created inside a source-media directory.
            source_root = Path(source["path"]).resolve()
            output = target.resolve()
            if output == source_root or source_root in output.parents:
                raise InventoryError("receipt must be outside source frame directory")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2, sort_keys=True)
                stream.write("\n")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
