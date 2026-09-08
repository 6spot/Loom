"""Offline archive invariants; fixtures are test pixels, never historical artwork."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib


HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("background_library", HERE / "library.py")
library = importlib.util.module_from_spec(spec)
spec.loader.exec_module(library)


def test_png():
    def chunk(name, content):
        return struct.pack(">I", len(content)) + name + content + struct.pack(">I", zlib.crc32(name + content))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0\xf5\xf1\xe8")) + chunk(b"IEND", b""))


class DraftArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "an image with spaces.png"
        self.image.write_bytes(test_png())
        self.store = self.root / "another-project" / "art"
        self.brief = json.loads((HERE.parent / "assets" / "brief.json").read_text(encoding="utf-8"))

    def add(self, brief=None, prompt="A real retained prompt for this test fixture."):
        return library.archive(self.store, self.image, brief or self.brief, prompt)

    def test_round_trip_preserves_bytes_prompt_and_stays_draft(self):
        result = self.add()
        self.assertEqual(Path(result["image_path"]).read_bytes(), test_png())
        self.assertEqual(Path(result["prompt_path"]).read_text(), "A real retained prompt for this test fixture.")
        self.assertEqual(result["manifest"]["status"], "draft")
        self.assertEqual(library.read_record(self.store, result["manifest"]["asset_id"], True)["brief"], self.brief)

    def test_duplicate_is_idempotent_and_new_prompt_keeps_old_version(self):
        first = self.add()
        repeated = self.add()
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(first["manifest"], repeated["manifest"])
        derived = deepcopy(self.brief)
        derived["derived_from"] = first["manifest"]["asset_id"]
        second = self.add(derived, "Make the river cooler.")
        self.assertNotEqual(first["manifest"]["asset_id"], second["manifest"]["asset_id"])
        self.assertEqual(len(library.list_records(self.store, verify=True)), 2)

    def test_concurrent_archive_has_one_complete_candidate(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.add(), range(8)))
        self.assertEqual(len({result["manifest"]["asset_id"] for result in results}), 1)
        self.assertEqual(sum(not result["duplicate"] for result in results), 1)
        self.assertEqual(len(library.list_records(self.store, verify=True)), 1)

    def test_cli_archive_search_and_verified_lookup(self):
        brief_path = self.root / "brief.json"
        prompt_path = self.root / "prompt.txt"
        brief_path.write_text(json.dumps(self.brief), encoding="utf-8")
        prompt_path.write_text("Retained CLI fixture prompt.", encoding="utf-8")
        command = [sys.executable, str(HERE / "library.py"), "--library", str(self.store)]

        def run(*arguments):
            result = subprocess.run(command + list(arguments), check=True, capture_output=True, text=True)
            return json.loads(result.stdout)

        saved = run("archive", "--image", str(self.image), "--brief", str(brief_path), "--prompt", str(prompt_path))
        found = run("list", "--query", "赤壁")
        self.assertEqual(found[0]["asset_id"], saved["manifest"]["asset_id"])
        opened = run("show", found[0]["asset_id"])
        self.assertEqual(Path(opened["image_path"]).read_bytes(), test_png())
        self.assertEqual(run("verify"), {"verified_drafts": 1, "valid": True})

    def test_metadata_search_supports_other_eras_and_library_paths(self):
        self.add()
        modern = deepcopy(self.brief)
        modern.update(title="民国城市", era="民国·1930年代", style="书刊水彩", tags=["城市", "青灰"],
                      proposed_placement="建议在上海城市叙述中使用，待人工确认")
        modern["subject"] = {"kind": "place", "name": "上海"}
        self.add(modern)
        self.assertEqual(len(library.list_records(self.store, query="赤壁")), 1)
        results = library.list_records(self.store, era="民国", kind="place")
        self.assertEqual(results[0]["brief"]["subject"]["name"], "上海")
        self.assertEqual(library.list_records(self.store, query="未收录题材"), [])

    def test_uploaded_image_does_not_invent_a_generation_prompt(self):
        upload = deepcopy(self.brief)
        upload["origin"] = {"kind": "uploaded", "rights": "用户自有插画", "tool": None, "model": None}
        result = self.add(upload, None)
        self.assertIn("未提供", Path(result["prompt_path"]).read_text())
        with self.assertRaises(ValueError):
            self.add(prompt=None)

    def test_corruption_is_reported_instead_of_overwritten(self):
        result = self.add()
        Path(result["image_path"]).write_bytes(b"broken")
        with self.assertRaisesRegex(ValueError, "integrity"):
            library.read_record(self.store, result["manifest"]["asset_id"], verify=True)
        with self.assertRaises(ValueError):
            self.add()
        self.assertEqual(Path(result["image_path"]).read_bytes(), b"broken")

    def test_no_brief_can_enable_or_publish_an_image(self):
        for field in ("status", "published", "approved", "public_url"):
            brief = deepcopy(self.brief)
            brief[field] = "enabled"
            with self.assertRaisesRegex(ValueError, "approval/display"):
                self.add(brief)
        self.assertFalse((self.store / "drafts").exists())

    def test_path_escape_and_linked_files_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid asset ID"):
            library.read_record(self.store, "../../outside")
        result = self.add()
        original = Path(result["image_path"])
        original.unlink()
        original.symlink_to(self.image)
        with self.assertRaisesRegex(ValueError, "symlink"):
            library.read_record(self.store, result["manifest"]["asset_id"], verify=True)

    def test_invalid_image_and_missing_parent_create_no_record(self):
        self.image.write_bytes(b"not a picture")
        with self.assertRaisesRegex(ValueError, "PNG"):
            self.add()
        self.image.write_bytes(test_png())
        self.brief["derived_from"] = "bg_" + "0" * 24
        with self.assertRaises(FileNotFoundError):
            self.add()
        self.assertFalse((self.store / "drafts").exists())


if __name__ == "__main__":
    unittest.main()
