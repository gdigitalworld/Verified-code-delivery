"""Tests for tools/build_skill.py."""
import hashlib
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from test_scripts import make_symlink  # noqa: E402

import build_skill  # noqa: E402  # type: ignore[reportMissingImports]


class BuildSkillTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def copy_skill(self) -> Path:
        dest = self.tmp / "verified-code-delivery"
        shutil.copytree(build_skill.SKILL_DIR, dest)
        return dest

    def test_real_skill_is_valid(self):
        self.assertEqual(build_skill.validate(build_skill.SKILL_DIR), [])

    def test_build_is_reproducible(self):
        a = build_skill.build(build_skill.SKILL_DIR, self.tmp / "a")
        b = build_skill.build(build_skill.SKILL_DIR, self.tmp / "b")
        self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(), hashlib.sha256(b.read_bytes()).hexdigest())

    def test_archive_layout_and_exclusions(self):
        skill = self.copy_skill()
        (skill / "scripts" / "__pycache__").mkdir(exist_ok=True)
        (skill / "scripts" / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"junk")
        target = build_skill.build(skill, self.tmp / "out")
        with zipfile.ZipFile(target) as z:
            names = z.namelist()
        self.assertEqual(names, sorted(names))
        self.assertIn("verified-code-delivery/SKILL.md", names)
        self.assertTrue(all(n.startswith("verified-code-delivery/") for n in names))
        self.assertFalse(any("__pycache__" in n or n.endswith(".pyc") for n in names))

    def test_validation_catches_bad_frontmatter(self):
        skill = self.copy_skill()
        md = skill / "SKILL.md"
        text = md.read_text(encoding="utf-8")
        md.write_text(text.replace("name: verified-code-delivery", "name: Wrong Name", 1), encoding="utf-8")
        self.assertTrue(build_skill.validate(skill))
        md.write_text("no frontmatter here", encoding="utf-8")
        self.assertTrue(build_skill.validate(skill))

    def test_validation_rejects_symlinks(self):
        skill = self.copy_skill()
        make_symlink(skill / "scripts" / "link.py", skill / "SKILL.md")
        self.assertTrue(any("symlink" in e for e in build_skill.validate(skill)))


if __name__ == "__main__":
    unittest.main()
