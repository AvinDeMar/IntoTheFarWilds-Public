#!/usr/bin/env python3
"""Offline regression checks for release boundaries and deterministic exports."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

spec = importlib.util.spec_from_file_location("publisher", Path(__file__).with_name("publish_art.py"))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.public = self.base / "public"
        self.public.mkdir()
        self.private = self.base / "private"
        self.private.mkdir()
        self.root_patch = patch.object(p, "ROOT", self.public)
        self.root_patch.start()
        self.selection = self.private / "selection.json"
        self.master = self.private / "master.png"
        image = Image.new("RGBA", (1024, 1024))
        image.paste((160, 100, 40, 255), (112, 212, 912, 812))
        image.save(self.master)
        self.items = [self.item("RES_EXAMPLE", 0), self.item("RES_SECOND", 1)]

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def item(self, cid, order):
        return dict(id=cid, name=cid, display_name=cid, kind="icon", category="resources",
                    group="Example", group_slug="01-example", group_order=1,
                    item_order=order, version="v001", source_path=str(self.master),
                    source_sha256=p.sha(self.master.read_bytes()), approval_status="Approved",
                    rights_status="cleared")

    def prepare(self, items=None, release="test.1"):
        self.selection.write_bytes(p.encoded({"items": self.items if items is None else items}))
        with contextlib.redirect_stdout(io.StringIO()):
            p.prepare(SimpleNamespace(selection=self.selection, state=None, release=release, date="2026-01-01"))

    def complete(self):
        for name in p.STATIC_FILES:
            target = self.public / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fixture\n")
        with contextlib.redirect_stdout(io.StringIO()):
            p.seal(None)
        return p.verify(SimpleNamespace(private_profile=None, expected_icons=2))

    def snapshot(self):
        return {f.relative_to(self.public).as_posix(): (p.sha(f.read_bytes()), f.stat().st_mtime_ns)
                for f in self.public.rglob("*") if f.is_file()}

    def test_exact_crop_and_alpha_aware_resize(self):
        outputs = p.derivatives(self.master, "icon")
        for (raw, dimensions), size in zip(outputs, [(100, 80), (400, 320)]):
            with Image.open(io.BytesIO(raw)) as im:
                self.assertEqual(im.size, size)
                self.assertEqual(im.mode, "RGBA")
                self.assertFalse(im.info)
                self.assertEqual(im.getpixel((0, 0))[3], 0)
                self.assertEqual(im.getpixel((size[0] // 2, size[1] // 2)), (160, 100, 40, 255))
                # x=112 in the square becomes x=10 after the exact live crop.
                self.assertGreater(im.getpixel((int(size[0] * .11), size[1] // 2))[3], 240)

    def test_idempotency_and_one_item_update(self):
        self.prepare()
        before = self.snapshot()
        self.prepare()
        self.assertEqual(before, self.snapshot())
        second = p.read_catalog()["items"][1]
        revised = self.private / "revised.png"
        image = Image.open(self.master).copy()
        image.paste((110, 120, 130, 255), (112, 212, 912, 812))
        image.save(revised)
        item = dict(self.items[0], source_path=str(revised), source_sha256=p.sha(revised.read_bytes()), version="v002")
        self.prepare([item], "test.2")
        after = self.snapshot()
        for label in ("thumbnail", "preview"):
            path = second[label]["path"]
            self.assertEqual(before[path], after[path])
        self.assertEqual(p.read_catalog()["items"][1], second)
        self.assertEqual(len(p.read_catalog()["items"]), 2)
        self.assertEqual(p.read_catalog()["items"][0]["thumbnail"]["path"], p.image_path(item, "thumbnail"))

    def test_rights_or_hash_failure_writes_nothing(self):
        for changes in ({"rights_status": "unresolved"}, {"source_sha256": "0" * 64}):
            with self.assertRaises(ValueError):
                self.prepare([self.items[0], dict(self.items[1], **changes)])
            self.assertEqual(self.snapshot(), {})

    def test_missing_derivative_restores_without_new_release(self):
        self.prepare()
        item = p.read_catalog()["items"][0]
        path = self.public / item["preview"]["path"]
        original = path.read_bytes()
        path.unlink()
        self.prepare()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(p.read_catalog()["releases"], ["test.1"])

    def test_group_collision_writes_nothing(self):
        with self.assertRaises(ValueError):
            self.prepare([self.items[0], dict(self.items[1], group_slug="02-different")])
        self.assertEqual(self.snapshot(), {})

    def test_allowlist_and_tampering_fail_closed(self):
        self.prepare()
        self.complete()
        unexpected = self.public / "unexpected.txt"
        unexpected.write_text("not selected", encoding="utf-8")
        with self.assertRaises(ValueError):
            p.seal(None)
        unexpected.unlink()
        path = self.public / p.read_catalog()["items"][0]["preview"]["path"]
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(ValueError):
            p.verify(SimpleNamespace(private_profile=None, expected_icons=2))

    def test_approval_gate_prevents_network(self):
        args = SimpleNamespace(approval=None, private_profile=None, expected_icons=2, dry_run=False)
        with patch.object(p.subprocess, "check_output", side_effect=AssertionError("network forbidden")), self.assertRaises(ValueError):
            p.publish(args)
        self.prepare()
        self.complete()
        receipt = self.private / "approval.json"
        receipt.write_bytes(p.encoded({"approved": True, "catalog_sha256": "wrong"}))
        args.approval = receipt
        with patch.object(p, "git", return_value=b""), patch.object(p.subprocess, "check_output", side_effect=AssertionError("network forbidden")), self.assertRaises(ValueError):
            p.publish(args)

    def test_retirement_preserves_other_items_and_blocks_escape(self):
        self.prepare()
        before = self.snapshot()
        args = SimpleNamespace(ids="RES_EXAMPLE", release="../escape", date="2026-01-01")
        with self.assertRaises(ValueError):
            p.retire(args)
        self.assertEqual(before, self.snapshot())
        args.release = "test.2"
        with contextlib.redirect_stdout(io.StringIO()):
            p.retire(args)
        self.assertEqual([i["id"] for i in p.read_catalog()["items"]], ["RES_SECOND"])
        self.assertEqual(p.read_catalog()["retired"][0]["id"], "RES_EXAMPLE")
        for path in before:
            if "res_second" in path:
                self.assertEqual(before[path], self.snapshot()[path])

    def test_external_inputs_and_path_containment(self):
        with self.assertRaises(ValueError):
            p.private_path(self.public / "selection.json")
        with self.assertRaises(ValueError):
            p.safe_path(self.public, "../outside")


if __name__ == "__main__":
    unittest.main(verbosity=2)
