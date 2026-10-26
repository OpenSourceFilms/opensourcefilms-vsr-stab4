"""Offline stdlib validation and future OpenCV execution tests for frozen STAB4."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import vsr_stab4_engine_v1 as engine


def png(path, width, height, bit_depth=16, colour=2, marker=0):
    channels = 3 if colour == 2 else 4
    stride = channels * (2 if bit_depth == 16 else 1)
    row = bytearray()
    for x in range(width):
        for ch in range(channels):
            n = ((x * 19 + marker * 31 + ch * 73) % (65536 if bit_depth == 16 else 256))
            row.extend(n.to_bytes(2 if bit_depth == 16 else 1, "big"))
    raw = b"".join(b"\x00" + bytes(row) for _ in range(height))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    content = (engine.PNG_MAGIC + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, colour, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    path.write_bytes(content)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="vsr_stab4_test_", dir=str(Path(__file__).resolve().parent.parent))
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.source = self.root / "source"
        self.enhanced = self.root / "enhanced"
        self.output = self.root / "result"
        self.source.mkdir()
        self.enhanced.mkdir()
        self.raw = {
            "schema": engine.SCHEMA, "shot_id": "TEST",
            "source_dir": str(self.source), "enhanced_dir": str(self.enhanced),
            "output_dir": str(self.output), "first_frame": 5,
            "frame_count": 3, "source_width": 8, "source_height": 4,
            "target_width": 16, "target_height": 8,
            "fps_num": 24, "fps_den": 1, "source_frame_offset": -5,
            "enhanced_frame_offset": -5
        }
        for i in range(3):
            png(self.source / engine.frame_name(i), 8, 4, marker=i)
            png(self.enhanced / engine.frame_name(i), 16, 8, marker=i + 1)

    def config(self):
        return engine.validate(self.raw)

    def test_canonical_index_and_frame_mapping(self):
        c = self.config()
        self.assertEqual(engine.frame_paths(c, 5)[0].name, "f0000.png")
        self.assertEqual(engine.frame_paths(c, 7)[1].name, "f0002.png")
        self.assertEqual(c["radius"], 4)
        self.assertEqual(engine.validate(c), c)
        self.assertEqual(engine.digest(c), engine.digest(dict(reversed(list(c.items())))))

    def test_input_filename_patterns_without_copying_media(self):
        default = self.config()
        original_id = engine.digest(default)
        self.assertNotIn("source_frame_pattern", default)
        self.assertEqual(engine.frame_paths(default, 5)[0].name, "f0000.png")
        for i in range(3):
            (self.source / engine.frame_name(i)).rename(self.source / f"{i:06d}.png")
            (self.enhanced / engine.frame_name(i)).rename(self.enhanced / f"frame_{i:05d}_.png")
        self.raw["source_frame_pattern"] = "%06d.png"
        self.raw["enhanced_frame_pattern"] = "frame_%05d_.png"
        cfg = self.config()
        self.assertNotEqual(original_id, engine.digest(cfg))
        self.assertEqual(engine.frame_paths(cfg, 5)[0].name, "000000.png")
        self.assertEqual(engine.frame_paths(cfg, 7)[1].name, "frame_00002_.png")
        self.assertEqual(len(engine.input_inventory(cfg)), 3)
        with self.assertRaisesRegex(ValueError, "unsafe frame filename"):
            engine.validate(dict(self.raw, source_frame_pattern="../%06d.png"))
        with self.assertRaisesRegex(ValueError, "unsafe frame filename"):
            engine.validate(dict(self.raw, enhanced_frame_pattern="%s.png"))

    def test_range_any_length_and_header(self):
        c = self.config()
        self.assertEqual(len(engine.input_inventory(c)), 3)
        self.assertEqual(engine.png_header(self.source / "f0000.png", (8, 4))["bit_depth"], 16)
        self.raw["frame_count"] = 100
        with self.assertRaisesRegex(ValueError, "missing/non-regular"):
            engine.input_inventory(self.config())

    def test_prepare_resume_is_read_only_on_existing_journal(self):
        c = self.config()
        first = engine.prepared(c, False)
        self.assertEqual(len(first["inputs"]), 3)
        self.assertEqual(first["status"], "PREPARED")
        self.assertEqual(engine.prepared(c, True), first)
        with self.assertRaisesRegex(ValueError, "specify --resume"):
            engine.prepared(c, False)
        with self.assertRaisesRegex(ValueError, "missing/extra"):
            engine.verify(c)

    def test_refuse_tampered_source_on_resume(self):
        c = self.config()
        engine.prepared(c, False)
        png(self.source / "f0001.png", 8, 4, marker=999)
        with self.assertRaisesRegex(ValueError, "changed"):
            engine.prepared(c, True)

    def test_verified_rgb48_and_output_tampering(self):
        c = self.config()
        entry = engine.prepared(c, False)
        for k in range(5, 8):
            out = self.output / engine.frame_name(k)
            png(out, 16, 8, marker=k)
            entry["outputs"][str(k)] = {"sha256": engine.sha256_file(out)}
        entry["status"] = "VERIFY_READY"
        engine.atomic_json(engine.index_path(c), entry)
        self.assertEqual(engine.verify(c)["frames"], 3)
        (self.output / "f0006.png").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "missing/modified"):
            engine.verify(c)

    def test_refuse_alpha_and_wrong_geometry(self):
        c = self.config()
        png(self.source / "f0001.png", 8, 4, colour=6)
        with self.assertRaisesRegex(ValueError, "noninterlaced"):
            engine.input_inventory(c)
        png(self.source / "f0001.png", 7, 4)
        with self.assertRaisesRegex(ValueError, "expected dimensions"):
            engine.input_inventory(c)

    def test_refuse_noncanonical_request(self):
        for update in (
            {"radius": 2}, {"target_width": 15}, {"frame_count": True},
            {"output_dir": str(self.source / "nested")}, {"output_dir": str(self.root)},
            {"fps_num": 0}, {"source_frame_offset": -8},
            {"unknown_param": 1}, {"shot_id": "../escape"},
            {"source_dir": "relative/path"}, {"frame_count": 0},
        ):
            req = dict(self.raw, **update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                engine.validate(req)

    def test_refuse_symlink_source_png(self):
        link = self.source / "f0001.png"
        link.unlink()
        link.symlink_to(self.enhanced / "f0001.png")
        with self.assertRaises(ValueError):
            engine.input_inventory(self.config())

    def test_refuse_preexisting_output_tree(self):
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, "output path must be absent"):
            engine.prepared(self.config(), False)

    def test_refuse_stale_atomic_journal_temp(self):
        c = self.config()
        self.output.mkdir()
        (self.output / "run_index.json.writing").write_text("unfinished")
        with self.assertRaisesRegex(ValueError, "stale journal temp"):
            engine.atomic_json(engine.index_path(c), {"not": "allowed"})

    def test_inprocess_partial_run_and_resume(self):
        c = self.config()
        def fake_work(task):
            cfg, k = task
            path = Path(cfg["output_dir"]) / (engine.frame_name(k)[:-4] + ".rendering.png")
            png(path, 16, 8, marker=k)
            return {"frame": k, "tmp": str(path), "sha256": engine.sha256_file(path),
                    "metrics": {"h": 1.0, "eff_frames": 1.0}}
        with patch.object(engine, "workers_for", return_value=(1, 123, 999999)), \
             patch.object(engine, "stabilise_one", side_effect=fake_work), \
             patch.object(engine, "ProcessPoolExecutor", side_effect=AssertionError("unexpected fork")):
            part = engine.run(c, selected_frames=[5])
            self.assertEqual(part["status"], "PARTIAL")
            self.assertEqual(part["frames_complete"], 1)
            final = engine.run(c, resume=True, selected_frames=[6, 7])
            self.assertEqual(final["frames"], 3)
            self.assertEqual(final["status"], "VERIFY_READY")
        with patch.object(engine, "workers_for", return_value=(1, 123, 999999)), \
             patch.object(engine, "stabilise_one", side_effect=AssertionError("must skip completed")):
            self.assertEqual(engine.run(c, resume=True, selected_frames=[5])["frames"], 3)

    def test_interrupted_temp_is_preserved_and_recovered(self):
        c = self.config()
        engine.prepared(c, False)
        orphan = self.output / "f0005.rendering.png"
        png(orphan, 16, 8, marker=111)
        def fake_work(task):
            cfg, k = task
            path = Path(cfg["output_dir"]) / (engine.frame_name(k)[:-4] + ".rendering.png")
            png(path, 16, 8, marker=k)
            return {"frame": k, "tmp": str(path), "sha256": engine.sha256_file(path),
                    "metrics": {}}
        with patch.object(engine, "workers_for", return_value=(1, 123, 999999)), \
             patch.object(engine, "stabilise_one", side_effect=fake_work):
            result = engine.run(c, resume=True, selected_frames=[5])
        self.assertEqual(result["status"], "PARTIAL")
        self.assertFalse(orphan.exists())
        self.assertTrue((self.output / "f0005.abandoned.001.png").exists())
        data = json.loads(engine.index_path(c).read_text())
        self.assertEqual(len(data["retained_orphans"]), 1)
        self.assertIn("5", data["outputs"])

    def test_resource_admission(self):
        c = self.config()
        with patch.object(engine, "cpu_count", return_value=3), patch.object(engine, "memory_free", return_value=1024**3):
            self.assertEqual(engine.workers_for(c)[0], 3)
            self.assertEqual(engine.workers_for(c, 1)[0], 1)
            with self.assertRaises(ValueError):
                engine.workers_for(c, 4)
        with patch.object(engine, "memory_free", return_value=1):
            with self.assertRaises(RuntimeError):
                engine.workers_for(c)

    @unittest.skipUnless(importlib.util.find_spec("cv2") and importlib.util.find_spec("numpy"), "native Work sandbox lacks OpenCV/NumPy")
    def test_single_frame_run_with_real_opencv(self):
        c = dict(self.raw, frame_count=1)
        c = engine.validate(c)
        with patch.object(engine, "cpu_count", return_value=1), patch.object(engine, "memory_free", return_value=1024**3):
            receipt = engine.run(c)
        self.assertEqual(receipt["frames"], 1)
        self.assertEqual(receipt["status"], "VERIFY_READY")
        self.assertEqual(engine.verify(c)["frames"], 1)


if __name__ == "__main__":
    unittest.main()
