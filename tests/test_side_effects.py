"""Tests for tool side effects, ANSI-free reports and workspace package managers."""
import json
import shutil
import sys
import unittest

from test_scripts import SCRIPTS, TmpDirCase, run, write

sys.path.insert(0, str(SCRIPTS))

import detect_checks  # noqa: E402
import verify  # noqa: E402


class AnsiTests(TmpDirCase):
    def test_colour_codes_are_stripped_from_failure_output(self):
        py = sys.executable
        cmd = f"\"{py}\" -c \"import sys; print('\\x1b[31mred error\\x1b[0m'); sys.exit(1)\""
        r = verify.run_step({"kind": "build", "stack": "x", "cwd": ".", "cmd": cmd}, self.root, 30)
        self.assertEqual(r["status"], "failed")
        self.assertIn("red error", r["tail"])
        self.assertNotIn("\x1b", r["tail"])


class WorkspacePackageManagerTests(TmpDirCase):
    def test_packages_inherit_the_workspace_package_manager(self):
        write(self.root, "package.json", json.dumps({"name": "root", "private": True}))
        write(self.root, "pnpm-workspace.yaml", "packages:\n  - 'packages/*'\n")
        write(self.root, "packages/a/package.json",
              json.dumps({"name": "a", "scripts": {"build": "x", "test": "y"}}))
        cmds = [(s["cmd"], s["cwd"]) for s in detect_checks.detect(self.root)]
        self.assertIn(("pnpm install", "."), cmds)
        self.assertIn(("pnpm run build", "packages/a"), cmds)
        self.assertIn(("pnpm run test", "packages/a"), cmds)
        self.assertFalse(any(c.startswith("npm ") for c, _ in cmds))


@unittest.skipUnless(shutil.which("npm"), "npm not installed")
class SideEffectTests(TmpDirCase):
    """A build step that rewrites an existing file and creates a new one,
    like `next build` rewriting tsconfig.json."""

    ORIGINAL = '{"strict": true}\n'

    def make(self):
        script = ("node -e \"const fs=require('fs');"
                  "fs.writeFileSync('config.json','{\\\"strict\\\": false}');"
                  "fs.writeFileSync('generated.txt','x')\"")
        write(self.root, "package.json", json.dumps({"name": "t", "version": "1.0.0", "scripts": {"build": script}}))
        write(self.root, "config.json", self.ORIGINAL)

    def test_side_effects_are_reported_but_left_alone_by_default(self):
        self.make()
        res = run("verify.py", self.root, "--skip", "install", "--timeout", "60")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("MODIFIED config.json", res.stdout)
        self.assertIn("NEW generated.txt", res.stdout)
        self.assertNotEqual((self.root / "config.json").read_text(), self.ORIGINAL)
        report = (self.root / ".verify" / "VERIFICATION.md").read_text()
        self.assertIn("Files changed by the checks themselves", report)
        effects = json.loads((self.root / ".verify" / "side_effects.json").read_text())
        self.assertEqual(effects["modified"], ["config.json"])
        self.assertEqual(effects["restored"], [])

    def test_restore_flag_puts_modified_files_back_byte_for_byte(self):
        self.make()
        res = run("verify.py", self.root, "--skip", "install", "--restore-side-effects", "--timeout", "60")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual((self.root / "config.json").read_text(), self.ORIGINAL)
        self.assertTrue((self.root / "generated.txt").exists(), "new files must be left, only reported")
        self.assertIn("MODIFIED config.json (restored)", res.stdout)
        effects = json.loads((self.root / ".verify" / "side_effects.json").read_text())
        self.assertEqual(effects["restored"], ["config.json"])


if __name__ == "__main__":
    unittest.main()
