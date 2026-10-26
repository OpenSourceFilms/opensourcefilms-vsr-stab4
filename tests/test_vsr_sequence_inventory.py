"""Synthetic-only tests for portable read-only PNG source lineage."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vsr_sequence_inventory as inv


def png(width=3, height=2, red=10, depth=8, colour=2):
    def chunk(kind, data):
        return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xffffffff)
    if colour == 2 and depth == 8:
        row = bytes([0]+[red,20,30]*width)
    elif colour == 6 and depth == 8:
        row = bytes([0]+[red,20,30,255]*width)
    elif colour == 2 and depth == 16:
        row = bytes([0])+b"".join(struct.pack(">HHH",red*256,20*256,30*256) for _ in range(width))
    else:
        raise ValueError("unsupported test PNG")
    header=struct.pack(">IIBBBBB",width,height,depth,colour,0,0,0)
    return inv.PNG_SIG+chunk(b"IHDR",header)+chunk(b"IDAT",zlib.compress(row*height))+chunk(b"IEND",b"")


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="vsr_inventory_public_")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.frames=self.root/"frames"
        self.frames.mkdir()
        for index in range(1,4):
            (self.frames/f"f{index:04d}.png").write_bytes(png(red=index+9))
        self.source={"kind":"sequence","path":str(self.frames),"frame_pattern":"f%04d.png",
                     "start_frame":1,"frame_count":3,"width":3,"height":2,
                     "bit_depth":8,"alpha":"none"}

    def test_hash_repeatable_and_source_unmodified(self):
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.frames.iterdir()}
        first=inv.inventory(self.source)
        second=inv.inventory(self.source)
        self.assertEqual(first,second)
        self.assertEqual(first["sequence_sha256"],inv.frame_fingerprint(first["frames"]))
        self.assertEqual(first["frame_count"],3)
        self.assertFalse(first["creative_approval"])
        self.assertFalse(first["production_write_allowed"])
        self.assertTrue(first["does_not_validate_png_crc_or_pixels"])
        self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.frames.iterdir()})

    def test_original_v1_fingerprint_format_unchanged(self):
        rows=inv.inventory(self.source)["frames"]
        wire="OSF-VSR-SOURCE-SEQUENCE-v1\n"+"".join("%d\t%s\t%s\n"%(r["frame_index"],r["filename"],r["sha256"]) for r in rows)
        self.assertEqual(inv.frame_fingerprint(rows),hashlib.sha256(wire.encode("ascii")).hexdigest())

    def test_frame_content_changes_identity(self):
        before=inv.inventory(self.source)["sequence_sha256"]
        (self.frames/"f0003.png").write_bytes(png(red=98))
        self.assertNotEqual(inv.inventory(self.source)["sequence_sha256"],before)

    def test_selected_window_excludes_other_files(self):
        before=inv.inventory(self.source)["sequence_sha256"]
        (self.frames/"not_selected.txt").write_text("not a frame")
        (self.frames/"f0005.png").write_bytes(png(red=99))
        self.assertEqual(inv.inventory(self.source)["sequence_sha256"],before)

    def test_missing_frame_rejected(self):
        (self.frames/"f0002.png").unlink()
        with self.assertRaisesRegex(inv.InventoryError,"missing"):
            inv.inventory(self.source)

    def test_png_geometry_and_depth_mismatch(self):
        for replacement in (png(width=9),png(depth=16)):
            with self.subTest(length=len(replacement)):
                (self.frames/"f0002.png").write_bytes(replacement)
                with self.assertRaisesRegex(inv.InventoryError,"geometry/depth"):
                    inv.inventory(self.source)

    def test_invalid_png_header_rejected(self):
        (self.frames/"f0001.png").write_bytes(b"not a PNG"*20)
        with self.assertRaisesRegex(inv.InventoryError,"signature"):
            inv.inventory(self.source)

    def test_rgba_labelled_opaque_refused(self):
        (self.frames/"f0001.png").write_bytes(png(colour=6))
        with self.assertRaisesRegex(inv.InventoryError,"alpha=none"):
            inv.inventory(self.source)

    def test_rgba_when_alpha_is_explicit(self):
        for i in range(1,4):
            (self.frames/f"f{i:04d}.png").write_bytes(png(colour=6))
        self.source["alpha"]="straight"
        out=inv.inventory(self.source)
        self.assertEqual(out["frames"][0]["png_colour_type"],6)

    def test_invalid_ihdr_chunk_length_is_not_a_valid_header(self):
        # An IHDR payload is always exactly 13 bytes. Do not advertise an
        # invalid chunk as a plausible PNG merely because bytes 16..25 look
        # like an ordinary PNG dimension/depth/colour header.
        for size in (0, 12, 14):
            with self.subTest(ihdr_length=size):
                malformed = bytearray(png())
                malformed[8:12] = struct.pack(">I", size)
                (self.frames/"f0001.png").write_bytes(malformed)
                with self.assertRaisesRegex(inv.InventoryError,"IHDR"):
                    inv.inventory(self.source)

    def test_rgb_cannot_claim_straight_or_premultiplied_alpha(self):
        # RGB colour type 2 does not store an alpha channel.
        for alpha in ("straight", "premultiplied"):
            with self.subTest(alpha=alpha):
                self.source["alpha"] = alpha
                with self.assertRaisesRegex(inv.InventoryError, "RGB.*alpha"):
                    inv.inventory(self.source)

    def test_unknown_alpha_is_valid_for_either_rgb_or_rgba(self):
        self.source["alpha"] = "unknown"
        first = inv.inventory(self.source)
        self.assertEqual(first["frames"][0]["png_colour_type"], 2)
        for i in range(1, 4):
            (self.frames/f"f{i:04d}.png").write_bytes(png(colour=6))
        second = inv.inventory(self.source)
        self.assertEqual(second["frames"][0]["png_colour_type"], 6)
        self.assertNotEqual(first["sequence_sha256"], second["sequence_sha256"])

    def test_symlinked_frame_refused(self):
        (self.frames/"f0002.png").unlink()
        (self.frames/"f0002.png").symlink_to(self.frames/"f0001.png")
        with self.assertRaisesRegex(inv.InventoryError,"symlink"):
            inv.inventory(self.source)

    def test_symlink_swap_after_precheck_cannot_hash_external_frame(self):
        # The old path.is_symlink() then Path.open() sequence was racy:
        # replace the checked frame just before os.open() and require that
        # O_NOFOLLOW blocks the external link rather than hashing its bytes.
        if not hasattr(os, "O_NOFOLLOW"):
            self.skipTest("no O_NOFOLLOW support")
        selected = self.frames / "f0002.png"
        outside = self.root / "outside_frame.png"
        outside.write_bytes(png(red=101))
        expected = outside.read_bytes()
        real_open = os.open
        swapped = []

        def swap_before_open(path, flags, *args, **kwargs):
            if Path(path) == selected and not swapped:
                selected.unlink()
                selected.symlink_to(outside)
                swapped.append(True)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(inv.os, "open", side_effect=swap_before_open):
            with self.assertRaisesRegex(inv.InventoryError, "safely open"):
                inv.inventory(self.source)
        self.assertEqual(swapped, [True])
        self.assertEqual(outside.read_bytes(), expected)
        self.assertTrue(selected.is_symlink())

    def test_pathname_replacement_during_read_invalidates_inventory(self):
        # The hook fires on the very first fdopen (frame 0001), so it must
        # replace *that* opened pathname, not a later file in the window.
        selected = self.frames / "f0001.png"
        old = selected.read_bytes()
        newer = png(red=111)
        real_fdopen = os.fdopen
        swapped = []

        def replace_after_open(fd, mode, *args, **kwargs):
            if not swapped:
                selected.unlink()
                selected.write_bytes(newer)
                swapped.append(True)
            return real_fdopen(fd, mode, *args, **kwargs)

        with mock.patch.object(inv.os, "fdopen", side_effect=replace_after_open):
            with self.assertRaisesRegex(inv.InventoryError, "changed while hashing"):
                inv.inventory(self.source)
        self.assertEqual(swapped, [True])
        self.assertNotEqual(selected.read_bytes(), old)
        self.assertEqual(selected.read_bytes(), newer)

    def test_swapped_fifo_is_refused_without_blocking(self):
        if not (hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK")
                and hasattr(os, "O_NOFOLLOW")):
            self.skipTest("POSIX FIFO/no-follow flags unavailable")
        selected = self.frames / "f0002.png"
        real_open = os.open
        swapped = []

        def swap_before_open(path, flags, *args, **kwargs):
            if Path(path) == selected and not swapped:
                selected.unlink()
                os.mkfifo(selected)
                swapped.append(True)
                self.assertTrue(flags & os.O_NONBLOCK)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(inv.os, "open", side_effect=swap_before_open):
            with self.assertRaisesRegex(inv.InventoryError, "non-regular"):
                inv.inventory(self.source)
        self.assertEqual(swapped, [True])

    def test_symlinked_source_directory_refused(self):
        alias=self.root/"alias"
        alias.symlink_to(self.frames,target_is_directory=True)
        self.source["path"]=str(alias)
        with self.assertRaisesRegex(inv.InventoryError,"symlink"):
            inv.inventory(self.source)

    def test_traversal_or_multiple_format_directives(self):
        for name in ("../f%04d.png","f%04d%s.png","%10000000d.png","f%d/part.png","f%04x.png"):
            with self.subTest(name=name):
                self.source["frame_pattern"]=name
                with self.assertRaisesRegex(inv.InventoryError,"frame_pattern"):
                    inv.inventory(self.source)

    def test_invalid_counts_and_types(self):
        for key,bad in (("frame_count",True),("frame_count",0),("start_frame",-1),
                        ("width",True),("height",-5),("bit_depth",12),("alpha","invented")):
            with self.subTest(key=key,bad=bad):
                src=dict(self.source);src[key]=bad
                with self.assertRaises(inv.InventoryError):
                    inv.inventory(src)

    def test_reject_untrusted_sequence_digest_entries(self):
        for row in ({"frame_index":0,"filename":"frame.png","sha256":"xx"},
                    {"frame_index":True,"filename":"frame.png","sha256":"a"*64},
                    {"frame_index":0,"filename":"../frame.png","sha256":"a"*64}):
            with self.assertRaises(inv.InventoryError):
                inv.frame_fingerprint([row])

    def test_source_window_different_start(self):
        src=dict(self.source);src["start_frame"]=2;src["frame_count"]=2
        out=inv.inventory(src)
        self.assertEqual([x["frame_index"] for x in out["frames"]],[2,3])
        self.assertNotEqual(out["sequence_sha256"],inv.inventory(self.source)["sequence_sha256"])

    def test_cli_create_only_receipt_and_no_source_mutation(self):
        config=self.root/"input.json";config.write_text(json.dumps(self.source))
        receipt=self.root/"receipts"/"fingerprint.json"
        cmd=[sys.executable,"-B",str(Path(inv.__file__)),str(config),"--receipt",str(receipt)]
        before={p.name:p.read_bytes() for p in self.frames.iterdir()}
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=12)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)["sequence_sha256"],json.loads(receipt.read_text())["sequence_sha256"])
        again=subprocess.run(cmd,capture_output=True,text=True,timeout=12)
        self.assertEqual(again.returncode,2)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.frames.iterdir()})

    def test_receipt_cannot_write_inside_source_directory(self):
        config=self.root/"config.json"
        config.write_text(json.dumps(self.source))
        receipt=self.frames/"private_receipt.json"
        cmd=[sys.executable,"-B",str(Path(inv.__file__)),str(config),"--receipt",str(receipt)]
        before={p.name:p.read_bytes() for p in self.frames.iterdir()}
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=12)
        self.assertEqual(p.returncode,2)
        self.assertIn("outside source frame",p.stderr)
        self.assertFalse(receipt.exists())
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.frames.iterdir()})

    def test_cli_bad_input_is_failure_not_success(self):
        config=self.root/"bad.json";config.write_text('{"kind": "wrong"}')
        p=subprocess.run([sys.executable,"-B",str(Path(inv.__file__)),str(config)],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,2)
        self.assertIn('"ok": false',p.stderr.lower())


if __name__ == "__main__":
    unittest.main()
