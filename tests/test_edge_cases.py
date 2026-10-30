"""Tests for: --project beyond the project cap, check_imports never reporting a false PASS
when it found no manifest, a missing toolchain reported as such, and eslint detection."""
import json
import os
import subprocess
import sys
import unittest

from test_scripts import SCRIPTS, TmpDirCase, run, write

sys.path.insert(0, str(SCRIPTS))

import detect_checks  # noqa: E402
import verify  # noqa: E402


def pkg(**fields) -> str:
    return json.dumps({"name": fields.pop("name", "x"), "version": "1.0.0", **fields})


class ProjectCapTests(TmpDirCase):
    def make(self, n=30):
        for i in range(1, n + 1):
            write(self.root, f"svc{i:02d}/package.json", pkg(name=f"svc{i}", scripts={"build": "x"}))

    def test_project_flag_reaches_a_project_beyond_the_cap(self):
        self.make()
        steps = detect_checks.detect(self.root, ["svc30"])
        self.assertTrue(steps, "no steps for a project past the cap")
        self.assertTrue(all(s["cwd"] == "svc30" for s in steps))

    def test_cap_still_applies_without_a_filter(self):
        self.make()
        cwds = {s["cwd"] for s in detect_checks.detect(self.root)}
        self.assertEqual(len(cwds), detect_checks.MAX_PROJECTS)

    def test_cli_has_no_cap_note_when_a_project_is_chosen(self):
        self.make()
        res = run("verify.py", self.root, "--project", "svc30", "--only", "nothing-matches")
        self.assertNotIn("only the first", res.stdout)


class NoManifestTests(TmpDirCase):
    def test_js_files_without_package_json_are_not_a_pass(self):
        write(self.root, "a.js", "const d = require('dayjs');\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("nothing checked", res.stdout)
        self.assertNotIn("PASS", res.stdout)

    def test_python_without_manifest_is_not_a_pass(self):
        write(self.root, "main.py", "import numpy\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 3, res.stdout)
        self.assertIn("nothing checked", res.stdout)
        self.assertNotIn("PASS", res.stdout)

    def test_partial_coverage_says_what_was_skipped(self):
        write(self.root, "package.json", pkg(dependencies={"zod": "3"}))
        write(self.root, "a.ts", "import z from 'zod';\n")
        write(self.root, "tool.py", "import numpy\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 0, res.stdout)
        self.assertIn("NOTE", res.stdout)
        self.assertIn("Python", res.stdout)

    def test_nested_manifest_only_still_checks_node(self):
        write(self.root, "web/package.json", pkg(dependencies={"zod": "3"}))
        write(self.root, "web/a.ts", "import l from 'lodash';\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("'lodash'", res.stdout)

    def test_project_with_nothing_to_check_passes(self):
        write(self.root, "README.md", "hi\n")
        self.assertEqual(run("check_imports.py", self.root).returncode, 0)


class MissingToolchainTests(TmpDirCase):
    @unittest.skipIf(sys.platform == "win32", "exit code 127 is a POSIX shell convention")
    def test_command_not_found_is_reported_as_missing_tool(self):
        r = verify.run_step({"kind": "build", "stack": "go", "cwd": ".",
                             "cmd": "definitely-not-a-real-command-xyz"}, self.root, 30)
        self.assertEqual(r["status"], "missing")
        self.assertEqual(r["exit_code"], 127)

    @unittest.skipIf(sys.platform == "win32", "exit code 127 is a POSIX shell convention")
    def test_report_explains_it_is_not_a_code_failure(self):
        # CI runners ship Go, Rust and Node, so the test must not rely on a tool being absent:
        # run with an empty PATH, where every tool is guaranteed to be missing.
        write(self.root, "go.mod", "module x\n")
        empty = self.root / "empty-bin"
        empty.mkdir()
        env = {**os.environ, "PATH": str(empty)}
        res = subprocess.run(
            [sys.executable, str(SCRIPTS / "verify.py"), str(self.root), "--timeout", "30",
             "--only", "build", "--out", str(self.root / "out")],
            env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        report = (self.root / "out" / "VERIFICATION.md").read_text()
        self.assertIn("MISSING", report)
        self.assertIn("not a code failure", report)


class EslintDetectTests(TmpDirCase):
    def lint(self):
        return [s["cmd"] for s in detect_checks.detect(self.root) if s["kind"] == "lint"]

    def test_flat_config_without_lint_script(self):
        write(self.root, "package.json", pkg(devDependencies={"eslint": "9"}))
        write(self.root, "eslint.config.js", "module.exports = [];\n")
        self.assertEqual(self.lint(), ["npx --no-install eslint ."])

    def test_lint_script_wins_over_config(self):
        write(self.root, "package.json", pkg(scripts={"lint": "x"}, devDependencies={"eslint": "9"}))
        write(self.root, "eslint.config.js", "")
        self.assertEqual(self.lint(), ["npm run lint"])

    def test_config_without_eslint_dependency_adds_nothing(self):
        write(self.root, "package.json", pkg())
        write(self.root, "eslint.config.js", "")
        self.assertEqual(self.lint(), [])


if __name__ == "__main__":
    unittest.main()
