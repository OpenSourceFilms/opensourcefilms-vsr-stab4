#!/usr/bin/env python3
"""Frozen Stage21/23 STAB4 port: source-flow stabilisation, no model inference.

CLI: python3 vsr_stab4_engine_v1.py probe|prepare|run|verify REQUEST.json [--resume] [--workers N]
Run preparation records all source and SeedVR2 hashes; outputs are create-only and
journalled per frame. An output is never accepted merely because its name exists.
This is a mathematical port, NOT accepted as golden-equivalent until native RGB48
parity testing. Requires numpy+opencv-python for 'run', stdlib for other operations.
"""
import argparse
import hashlib
import json
import math
import os
import re
import struct
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

SCHEMA = "osf.vsr.stab4_request.v1"
INDEX_SCHEMA = "osf.vsr.stab4_run.v1"
ENGINE = "stage21_radius4_frozen_port_v1"
REQUIRED = ("schema", "shot_id", "source_dir", "enhanced_dir", "output_dir",
            "first_frame", "frame_count", "source_width", "source_height",
            "target_width", "target_height", "fps_num", "fps_den")
PNG_MAGIC = bytes.fromhex("89504e470d0a1a0a")
NAME_RE = re.compile(r"^f[0-9]{4,}.png$")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def frame_name(frame):
    if frame < 0:
        raise ValueError("negative frame index")
    return f"f{frame:04d}.png"


def input_name(config, key, frame):
    if frame < 0:
        raise ValueError("negative input frame index")
    pattern = config.get(key, "f%04d.png")
    return pattern % frame


def frame_paths(config, k):
    return (Path(config["source_dir"]) / input_name(config, "source_frame_pattern", k + config["source_frame_offset"]),
            Path(config["enhanced_dir"]) / input_name(config, "enhanced_frame_pattern", k + config["enhanced_frame_offset"]))


def validate(raw):
    if not isinstance(raw, dict):
        raise ValueError("request must be an object")
    extra = set(raw) - set(REQUIRED) - {"radius", "source_frame_offset", "enhanced_frame_offset", "source_colour", "enhanced_colour", "source_frame_pattern", "enhanced_frame_pattern"}
    if extra:
        raise ValueError("unrecognised request keys: " + ",".join(sorted(extra)))
    for key in REQUIRED:
        if key not in raw:
            raise ValueError("missing " + key)
    if raw["schema"] != SCHEMA:
        raise ValueError("unsupported request schema")
    if not isinstance(raw["shot_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", raw["shot_id"]):
        raise ValueError("invalid shot_id")
    config = dict(raw)
    for key in ("first_frame", "frame_count", "source_width", "source_height",
                "target_width", "target_height", "fps_num", "fps_den", "radius",
                "source_frame_offset", "enhanced_frame_offset"):
        if key not in config:
            config[key] = 4 if key == "radius" else 0
        if type(config[key]) is not int:
            raise ValueError(key + " must be an integer")
    if config["radius"] != 4:
        raise ValueError("this frozen STAB4 port requires radius=4")
    if config["first_frame"] < 0 or config["frame_count"] < 1:
        raise ValueError("invalid frame range")
    for key in ("source_width", "source_height", "target_width", "target_height", "fps_num", "fps_den"):
        if config[key] < 1:
            raise ValueError("non-positive " + key)
    if config["frame_count"] > 1000000:
        raise ValueError("frame count exceeds one million")
    if config["first_frame"] + config["source_frame_offset"] < 0 or config["first_frame"] + config["enhanced_frame_offset"] < 0:
        raise ValueError("input index underflow")
    sw, sh = config["source_width"], config["source_height"]
    tw, th = config["target_width"], config["target_height"]
    if tw < sw or th < sh or tw * sh != th * sw:
        raise ValueError("source/target aspect differs or target smaller; explicit crop is not supported")
    for key in ("source_colour", "enhanced_colour"):
        if key in config and (not isinstance(config[key], str) or len(config[key]) > 160):
            raise ValueError("invalid colour string")
    for key in ("source_frame_pattern", "enhanced_frame_pattern"):
        if key in config:
            pattern = config[key]
            if (not isinstance(pattern, str) or len(pattern) > 96
                    or not re.fullmatch(r"[A-Za-z0-9_.-]*%0?[0-9]{0,2}d[A-Za-z0-9_.-]*\.png", pattern)
                    or ".." in pattern or pattern.count("%") != 1):
                raise ValueError("unsafe frame filename pattern: " + key)
    paths = []
    for key in ("source_dir", "enhanced_dir", "output_dir"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError("missing directory " + key)
        raw_path = Path(config[key])
        if not raw_path.is_absolute():
            raise ValueError("absolute paths required")
        path = raw_path.resolve()
        config[key] = str(path)
        paths.append(path)
    src, enhanced, out = paths
    if src == enhanced:
        raise ValueError("source and enhanced directories must differ")
    for protected in (src, enhanced):
        if out == protected or protected in out.parents or out in protected.parents:
            raise ValueError("output overlaps input tree")
    return config


def parse_request(filename):
    with open(filename, encoding="utf-8") as f:
        return validate(json.load(f))


def png_header(path, expected_size):
    if not path.is_file() or path.is_symlink():
        raise ValueError("missing/non-regular or symlinked PNG: " + str(path))
    with open(path, "rb") as stream:
        blob = stream.read(33)
    if len(blob) < 33 or blob[:8] != PNG_MAGIC or blob[12:16] != b"IHDR":
        raise ValueError("invalid PNG header: " + str(path))
    # The PNG IHDR chunk must contain exactly 13 payload bytes. This is
    # deliberately a header-integrity check, not complete CRC/pixel decoding.
    if struct.unpack(">I", blob[8:12])[0] != 13:
        raise ValueError("invalid PNG IHDR chunk length: " + str(path))
    width, height, bits, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", blob[16:29])
    if (width, height) != expected_size or bits not in (8, 16) or colour != 2 or compression or filtering or interlace:
        raise ValueError("must be noninterlaced RGB8/RGB16 with expected dimensions: " + str(path))
    return {"width": width, "height": height, "bit_depth": bits, "colour_type": colour}


def input_inventory(config):
    receipts = {}
    for k in range(config["first_frame"], config["first_frame"] + config["frame_count"]):
        src, enhanced = frame_paths(config, k)
        receipts[str(k)] = {
            "source_file": src.name, "source_sha256": sha256_file(src) if png_header(src, (config["source_width"], config["source_height"])) else None,
            "enhanced_file": enhanced.name, "enhanced_sha256": sha256_file(enhanced) if png_header(enhanced, (config["target_width"], config["target_height"])) else None
        }
    return receipts


def atomic_json(path, obj):
    tmp = path.with_name(path.name + ".writing")
    if tmp.exists() or tmp.is_symlink():
        raise ValueError("stale journal temp must be inspected: " + str(tmp))
    try:
        with open(tmp, "x", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def index_path(config):
    return Path(config["output_dir"]) / "run_index.json"


def prepared(config, resume):
    root = Path(config["output_dir"])
    idx = index_path(config)
    if idx.is_file():
        if not resume:
            raise ValueError("run already exists: specify --resume")
        with open(idx, encoding="utf-8") as f:
            current = json.load(f)
        if current.get("schema") != INDEX_SCHEMA or current.get("config_sha256") != digest(config):
            raise ValueError("existing run identity mismatch")
        expected = input_inventory(config)
        if expected != current.get("inputs"):
            raise ValueError("source/SeedVR2 inputs changed since run preparation")
        return current
    if resume or root.exists() or root.is_symlink():
        raise ValueError("resume needs an existing valid run, or output path must be absent")
    inventory = input_inventory(config)
    root.mkdir(parents=True, exist_ok=False)
    current = {"schema": INDEX_SCHEMA, "engine": ENGINE, "config": config,
               "config_sha256": digest(config), "inputs": inventory,
               "outputs": {}, "status": "PREPARED"}
    atomic_json(idx, current)
    return current


def read_limit_int(path):
    try:
        raw = Path(path).read_text().strip()
        return int(raw) if raw not in ("max", "") else None
    except (ValueError, OSError):
        return None


def cpu_count():
    n = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            n = min(n, max(1, math.ceil(int(quota) / int(period))))
    except (OSError, ValueError):
        pass
    return max(1, n)


def memory_free():
    cap = read_limit_int("/sys/fs/cgroup/memory.max")
    used = read_limit_int("/sys/fs/cgroup/memory.current") or 0
    try:
        avail = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemAvailable:"))) * 1024
    except (OSError, StopIteration, ValueError):
        avail = 2147483648
    return min(avail, max(0, cap - used)) if cap else avail


def workers_for(config, requested=None):
    target_px = config["target_width"] * config["target_height"]
    source_px = config["source_width"] * config["source_height"]
    # Deliberately conservative bound for float32 sources, warped RGB, flow,
    # grids, remaps, and 8 temporal neighbours, plus 25% process headroom.
    est = int((target_px * (120 + 30 * config["radius"] * 2) + source_px * 200) * 1.25)
    free = memory_free()
    slots = min(cpu_count(), max(0, free // max(1, est)))
    if slots < 1:
        raise RuntimeError(f"insufficient advertised free RAM: {free} bytes; estimate {est} bytes per worker")
    if requested is not None:
        if requested < 1 or requested > slots:
            raise ValueError(f"requested workers={requested} exceeds admitted 1..{slots}")
        return requested, est, free
    return slots, est, free


def _cv():
    import cv2
    import numpy as np
    cv2.setNumThreads(4)  # frozen Stage21/23 setting
    return cv2, np


def _lo(path, cv2, np):
    a = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if a is None or a.ndim != 3 or a.shape[2] != 3 or a.dtype not in (np.uint8, np.uint16):
        raise ValueError("invalid source PNG " + str(path))
    return a.astype(np.float32) / (257.0 if a.dtype == np.uint16 else 1.0)


def _hi(path, cv2, np):
    a = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if a is None or a.ndim != 3 or a.shape[2] != 3 or a.dtype not in (np.uint8, np.uint16):
        raise ValueError("invalid enhanced PNG " + str(path))
    return a.astype(np.float32) / (257.0 if a.dtype == np.uint16 else 1.0)


def stabilise_one(task):
    cfg, k = task
    cv2, np = _cv()
    sw, sh = cfg["source_width"], cfg["source_height"]
    ow, oh = cfg["target_width"], cfg["target_height"]
    first, last = cfg["first_frame"], cfg["first_frame"] + cfg["frame_count"] - 1
    src_k, hi_k = frame_paths(cfg, k)
    g8 = lambda x: np.clip(x.mean(2), 0, 255).astype(np.uint8)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    Lk = _lo(src_k, cv2, np)
    Uk = cv2.resize(Lk, (ow, oh), interpolation=cv2.INTER_LANCZOS4)
    Dk = _hi(hi_k, cv2, np) - Uk
    gx, gy = np.meshgrid(np.arange(sw, dtype=np.float32), np.arange(sh, dtype=np.float32))
    GX, GY = np.meshgrid(np.arange(ow, dtype=np.float32), np.arange(oh, dtype=np.float32))
    items = []
    for j in range(max(first, k - cfg["radius"]), min(last, k + cfg["radius"]) + 1):
        if j == k:
            continue
        src_j, hi_j = frame_paths(cfg, j)
        Lj = _lo(src_j, cv2, np)
        f = dis.calc(g8(Lk), g8(Lj), None)
        e = cv2.GaussianBlur(np.abs(cv2.remap(Lj, gx + f[..., 0], gy + f[..., 1],
                     cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE) - Lk).mean(2), (0, 0), 1.5)
        F = cv2.resize(f, (ow, oh), interpolation=cv2.INTER_LINEAR) * (ow / float(sw))
        Dj = _hi(hi_j, cv2, np) - cv2.resize(Lj, (ow, oh), interpolation=cv2.INTER_LANCZOS4)
        items.append((j, e, cv2.remap(Dj, GX + F[..., 0], GY + F[..., 1],
                                           cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)))
    adj = [e for j, e, _ in items if abs(j-k) == 1]
    if adj:
        h = 2.0 * float(np.median(np.concatenate([e.ravel() for e in adj])))
        if not math.isfinite(h) or h <= 0.0:
            raise ValueError(f"frame {k}: zero/nonfinite flow-trust h; frozen formula undefined, no silent fallback")
    else:
        h = None  # one-frame clip: no temporal neighbours, same algebraic single-frame result
    num, den = Dk.copy(), np.ones((oh, ow), np.float32)
    wm = {}
    for j, e, WD in items:
        w = cv2.resize(np.exp(-(e / h) ** 2), (ow, oh), interpolation=cv2.INTER_LINEAR)
        num += w[..., None] * WD
        den += w
        wm[str(j - k)] = float(w.mean())
    out = Uk + num / den[..., None]
    if not np.isfinite(out).all():
        raise ValueError(f"frame {k}: nonfinite output; refused")
    dest = Path(cfg["output_dir"]) / frame_name(k)
    tmp = dest.with_name(dest.stem + ".rendering.png")
    if tmp.exists() or tmp.is_symlink():
        raise ValueError("stale rendering temp requires inspection: " + str(tmp))
    written = cv2.imwrite(str(tmp), np.clip(out * 257.0, 0, 65535).round().astype(np.uint16))
    if not written:
        raise IOError("PNG encode failed: " + str(tmp))
    return {"frame": k, "tmp": str(tmp), "sha256": sha256_file(tmp),
            "metrics": {"h": h, "mean_weight_by_offset": wm,
                        "eff_frames": float(den.mean()), "detail_rms_in": float(Dk.std()),
                        "detail_rms_out": float((num / den[..., None]).std())}}


def verify(config):
    idx = index_path(config)
    if not idx.is_file():
        raise ValueError("no run_index.json")
    run = json.loads(idx.read_text(encoding="utf-8"))
    if run.get("config_sha256") != digest(config) or run.get("schema") != INDEX_SCHEMA:
        raise ValueError("run index identity mismatch")
    if input_inventory(config) != run.get("inputs"):
        raise ValueError("input integrity mismatch")
    expected_names = {frame_name(k) for k in range(config["first_frame"], config["first_frame"] + config["frame_count"])}
    actual_names = {p.name for p in Path(config["output_dir"]).iterdir() if NAME_RE.fullmatch(p.name)}
    if actual_names != expected_names:
        raise ValueError("output sequence contains missing/extra canonical frames")
    count = 0
    for k in range(config["first_frame"], config["first_frame"] + config["frame_count"]):
        file = Path(config["output_dir"]) / frame_name(k)
        rec = run["outputs"].get(str(k))
        if not rec or rec.get("sha256") != sha256_file(file):
            raise ValueError("missing/modified output " + str(file))
        meta = png_header(file, (config["target_width"], config["target_height"]))
        if meta["bit_depth"] != 16:
            raise ValueError("output bit depth is not 16: " + str(file))
        count += 1
    return {"frames": count, "status": run["status"], "sha256": digest(run)}


def run(config, resume=False, requested_workers=None, selected_frames=None):
    frames = range(config["first_frame"], config["first_frame"] + config["frame_count"])
    selected = list(frames) if selected_frames is None else sorted(set(selected_frames))
    if not selected or any(k not in frames for k in selected):
        raise ValueError("selected frames must lie within complete shot contract")
    current = prepared(config, resume)
    slots, estimate, available = workers_for(config, requested_workers)
    outdir = Path(config["output_dir"])
    remaining = []
    for k in selected:
        dest = outdir / frame_name(k)
        old = current["outputs"].get(str(k))
        if old:
            # Resume must enforce the same regular-file contract as verify().
            # Never follow a symlink merely because its target matches a
            # recorded SHA-256 digest.
            if dest.is_symlink() or not dest.is_file():
                raise ValueError("recorded output is missing, symlinked or non-regular: " + str(dest))
            if sha256_file(dest) != old.get("sha256"):
                raise ValueError("recorded frame has changed: " + str(dest))
            continue
        # A terminated worker may leave an incomplete temporary PNG. Preserve
        # it as evidence, never treat it as complete or overwrite an image.
        orphan = outdir / (dest.stem + ".rendering.png")
        if orphan.exists() or orphan.is_symlink():
            if not resume or not orphan.is_file() or orphan.is_symlink():
                raise ValueError("untrusted rendering temp: " + str(orphan))
            for serial in range(1, 1000):
                retained = outdir / f"{dest.stem}.abandoned.{serial:03d}.png"
                if not retained.exists() and not retained.is_symlink():
                    orphan_sha = sha256_file(orphan)
                    orphan.rename(retained)
                    current.setdefault("retained_orphans", []).append(
                        {"path": retained.name, "sha256": orphan_sha})
                    break
            else:
                raise ValueError("too many retained orphan generations for " + str(dest))
        remaining.append(k)
    if not remaining:
        if len(current["outputs"]) == config["frame_count"]:
            return verify(config)
        return {"status": "PARTIAL", "frames_complete": len(current["outputs"]),
                "frame_count": config["frame_count"], "config_sha256": digest(config)}
    current["status"] = "RUNNING"
    atomic_json(index_path(config), current)
    tasks = ((config, k) for k in remaining)
    # Journals updated by parent only; worker writes unique .rendering.png temp.
    def commit(result):
        k, tmp, sha = result["frame"], Path(result["tmp"]), result["sha256"]
        dest = outdir / frame_name(k)
        if dest.exists() or dest.is_symlink():
            # Crash after previous atomic media creation but before journal update:
            # accept only a regular, non-symlink, byte-identical frame.
            if dest.is_symlink() or not dest.is_file():
                raise ValueError("orphaned destination is symlinked or non-regular: " + str(dest))
            if sha256_file(dest) != sha:
                raise ValueError("orphaned destination differs; refused overwrite: " + str(dest))
            tmp.unlink()
        else:
            os.replace(tmp, dest)
        current["outputs"][str(k)] = {"sha256": sha, "source_frame": k + config["source_frame_offset"],
                                     "enhanced_frame": k + config["enhanced_frame_offset"],
                                     "metrics": result["metrics"]}
        atomic_json(index_path(config), current)
    if slots == 1:
        # Kernel-sandboxed workers may forbid multiprocessing semaphores.
        # Direct execution preserves exact arithmetic and supports 2-vCPU pods.
        for result in map(stabilise_one, tasks):
            commit(result)
    else:
        with ProcessPoolExecutor(max_workers=slots) as pool:
            for result in pool.map(stabilise_one, tasks):
                commit(result)
    current["status"] = "VERIFY_READY" if len(current["outputs"]) == config["frame_count"] else "PARTIAL"
    atomic_json(index_path(config), current)
    if current["status"] == "VERIFY_READY":
        return verify(config)
    return {"status": "PARTIAL", "frames_complete": len(current["outputs"]),
            "frame_count": config["frame_count"], "config_sha256": digest(config)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("operation", choices=("probe", "prepare", "run", "verify"))
    ap.add_argument("request")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--only-frames", default=None,
                    help="comma-separated output frame indices, with full-shot temporal context")
    args = ap.parse_args(argv)
    cfg = parse_request(args.request)
    if args.operation == "probe":
        report = {"config_sha256": digest(cfg), "first_frame": cfg["first_frame"],
                  "frame_count": cfg["frame_count"], "geometry": [cfg["source_width"], cfg["source_height"],
                  cfg["target_width"], cfg["target_height"]], "status": "VALIDATED_NOT_RENDERED"}
    elif args.operation == "prepare":
        index = prepared(cfg, args.resume)
        report = {"config_sha256": index["config_sha256"], "input_frames": len(index["inputs"]), "status": index["status"]}
    elif args.operation == "run":
        selected = None
        if args.only_frames is not None:
            try:
                selected = [int(part) for part in args.only_frames.split(",")]
            except ValueError:
                raise ValueError("--only-frames requires comma-separated integers")
        report = run(cfg, args.resume, args.workers, selected)
    else:
        report = verify(cfg)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, KeyError) as e:
        print(type(e).__name__ + ": " + str(e), file=sys.stderr)
        sys.exit(2)
