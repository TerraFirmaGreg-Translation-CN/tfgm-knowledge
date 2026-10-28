import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tfgm_knowledge import snbt
from tfgm_knowledge.build import build, chunks, localize, search
from tfgm_knowledge.sources import core_tag, dependencies, digest, snapshot_path


class ParserTests(unittest.TestCase):
    def test_ftb_relaxed_snbt(self):
        data = snbt.loads('''{
          // No commas between FTB fields
          id: "00ABC" dependencies: ["0A" "0B"]
          count: 12L enabled: true position: -1.5d
          typed: [I; 1, 2, -3] item: minecraft:iron_ingot
          quoted: "你好\\n\\u5408金" nested: [{type: "item"}]
        }''')
        self.assertEqual(data["id"], "00ABC")
        self.assertEqual(data["dependencies"], ["0A", "0B"])
        self.assertEqual(data["typed"], [1, 2, -3])
        self.assertEqual(data["quoted"], "你好\n合金")
        self.assertEqual(data["position"], -1.5)

    def test_bad_input_rejected(self):
        for text in ('{a:1 a:2}', '{a: "oops}', '[1', '{} ignored', '/* oops'):
            with self.subTest(text=text), self.assertRaises(snbt.ParseError):
                snbt.loads(text)

    def test_localization_fallback_is_explicit(self):
        fallback, missing = set(), set()
        result = localize(["{quest.title}", "{missing}"], "zh_cn", {"en_us": {"quest.title": "Alloy"}}, fallback, missing)
        self.assertEqual(result, ["Alloy", "{missing}"])
        self.assertEqual(fallback, {"quest.title"})
        self.assertEqual(missing, {"missing"})

    def test_chunk_offsets_and_coverage(self):
        text = ("矿石合金\n" * 2000) + "END"
        parts = list(chunks(text))
        self.assertEqual(parts[0][0], 0)
        self.assertEqual(parts[-1][1], len(text))
        for i, (start, end, content) in enumerate(parts):
            self.assertEqual(content, text[start:end])
            if i:
                self.assertLessEqual(start, parts[i - 1][1])

    def test_dependency_platform_is_not_silently_substituted(self):
        data = {"projects": [{"pakku_id": "a", "files": [{"type": "modrinth", "file_name": "wrong.jar"}]}]}
        result = dependencies(data, "curseforge")
        self.assertEqual(result[0]["files"], [])
        self.assertEqual(result[0]["status"], "unavailable-on-selected-platform")

    def test_core_version_comes_from_selected_platform(self):
        data = {"projects": [{"files": [
            {"type": "curseforge", "file_name": "TerraFirmaGreg-Core-Modern-0.9.31.jar"},
            {"type": "modrinth", "file_name": "TerraFirmaGreg-Core-Modern-0.9.30.jar"}]}]}
        self.assertEqual(core_tag(data, "curseforge"), "0.9.31")


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.output = self.root / "dist"
        self.source = {"id": "modpack", "repository": "Example/Pack", "ref_policy": "release", "ref": "1.0",
                       "role": "gameplay", "include": ["/**"], "license": "NOASSERTION", "version_relation": "release-matched"}
        checkout = self.root / "checkout"
        checkout.mkdir()
        fixtures = {
            "config/ftbquests/quests/chapters/start.snbt": '{id:"CHAPTER" filename:"start" quests:[{id:"Q1" title:"{quest.title}" description:["{quest.body}"] tasks:[{id:"T1" type:"checkmark"}]} {id:"Q2" title:"Second" dependencies:["Q1"]}]}',
            "kubejs/assets/tfg/lang/en_us/quests/start.json": json.dumps({"quest.title": "Alloy", "quest.body": "An alloy furnace"}),
            "kubejs/assets/tfg/lang/zh_cn/quests/start.json": json.dumps({"quest.title": "合金", "quest.body": "合金炉的制作"}),
            "kubejs/assets/tfg/patchouli_books/field_guide/en_us/entries/metals.json": json.dumps({"name": "Metals", "pages": [{"type": "patchouli:text", "text": "$(bold)Alloy$() guide", "recipe": "tfg:alloy"}]}),
            "README.md": "# Fixture\n\nA document.\n",
        }
        for path, text in fixtures.items():
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        def git(*args):
            return subprocess.check_output(["git", "-C", str(checkout), *args], stderr=subprocess.DEVNULL, text=True).strip()
        git("init")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
        self.source["commit"] = git("rev-parse", "HEAD")
        self.snapshot = snapshot_path(self.cache, self.source)
        self.snapshot.parent.mkdir(parents=True)
        checkout.rename(self.snapshot)
        self.lock = {"schema_version": 1, "modpack_version": "1.0", "resolved_at": "2026-01-01T00:00:00Z",
                     "sources": [self.source], "dependencies": [], "exports": [], "config_sha256": digest({}),
                     "languages": ["en_us", "zh_cn"], "release": {"body": "Release", "url": "https://example.invalid/release"}}

    def tearDown(self):
        self.temp.cleanup()

    def test_bundle_search_provenance_and_reuse(self):
        directory, archive, reused = build(self.lock, self.cache, self.output)
        self.assertFalse(reused)
        self.assertTrue(archive.is_file())
        rows = search(directory / "knowledge.sqlite", "合金", kind="quest", language="zh_cn")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["data"]["quest_id"], "Q1")
        self.assertIn(self.source["commit"], rows[0]["source_url"])
        self.assertEqual(rows[0]["data"]["translation_sources"][0]["source"], "modpack")
        self.assertTrue(search(directory / "knowledge.sqlite", "furnace"))
        self.assertEqual(search(directory / "knowledge.sqlite", "' OR 1=1 --"), [])
        report = json.loads((directory / "report.json").read_text())
        self.assertEqual(report["warnings"], [])
        self.assertTrue(build(self.lock, self.cache, self.output)[2])

    def test_modified_snapshot_is_rejected(self):
        (self.snapshot / "README.md").write_text("changed")
        with self.assertRaisesRegex(ValueError, "Modified source snapshot"):
            build(self.lock, self.cache, self.output)
        self.assertFalse((self.output / "latest.json").exists())

    def test_failure_keeps_previous_bundle(self):
        build(self.lock, self.cache, self.output)
        previous = (self.output / "latest.json").read_bytes()
        new_lock = copy.deepcopy(self.lock)
        new_lock["exports"] = [{"status": "version-mismatch"}]
        with patch("tfgm_knowledge.build.create_database", side_effect=RuntimeError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "disk full"):
                build(new_lock, self.cache, self.output)
        self.assertEqual((self.output / "latest.json").read_bytes(), previous)
        self.assertFalse(list(self.output.glob(".build-*")))


if __name__ == "__main__":
    unittest.main()
