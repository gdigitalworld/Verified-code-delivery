"""Tests for: --project keeping the workspace install, syntax errors not hiding
import problems, and failing TAP tests surfacing at the top of the report."""
import json
import shutil
import sys
import unittest

from test_scripts import SCRIPTS, TmpDirCase, run, write

sys.path.insert(0, str(SCRIPTS))

import verify  # noqa: E402


class SyntaxErrorMaskingTests(TmpDirCase):
    def test_syntax_error_does_not_hide_undeclared_import(self):
        write(self.root, "requirements.txt", "requests\n")
        write(self.root, "bad.py", "import numpy\nfrom PIL import Image\ndef f(:\n    pass\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("syntax error", res.stdout)
        self.assertIn("'numpy'", res.stdout)
        self.assertIn("'PIL'", res.stdout)
        self.assertIn("1 syntax error(s)", res.stdout)  # heading says what kind of problem

    def test_heading_without_syntax_errors_is_unchanged_in_meaning(self):
        write(self.root, "requirements.txt", "requests\n")
        write(self.root, "a.py", "import numpy\n")
        res = run("check_imports.py", self.root)
        self.assertIn("1 undeclared import(s)", res.stdout)
        self.assertNotIn("syntax error(s)", res.stdout)


class FailureExcerptTests(unittest.TestCase):
    TAP = "\n".join(
        ["TAP version 13"]
        + [f"ok {i} - fine {i}" for i in range(1, 80)]
        + ["not ok 80 - ledger sums to 10",
           "  ---",
           "  error: 'Expected values to be strictly equal: 18 !== 10'",
           "  ...",
           "ok 81 - later test"]
        + [f"# noise line {i}" for i in range(60)]
        + ["# fail 1"])

    def test_not_ok_block_is_moved_to_top(self):
        out = verify.failure_excerpt(self.TAP)
        self.assertTrue(out.startswith("[failing tests]"))
        self.assertIn("18 !== 10", out.split("[end of output]")[0])
        self.assertIn("# fail 1", out)

    def test_plain_output_keeps_the_tail(self):
        text = "\n".join(f"line {i}" for i in range(100))
        out = verify.failure_excerpt(text)
        self.assertEqual(out.splitlines(), [f"line {i}" for i in range(60, 100)])

    def test_ansi_codes_are_removed(self):
        self.assertNotIn("\x1b", verify.failure_excerpt("\x1b[31mnot ok 1 - x\x1b[0m\n"))

    def test_many_failures_are_capped(self):
        text = "\n".join(f"not ok {i} - t{i}\n  ---\n  error: e{i}\n  ..." for i in range(100))
        self.assertIn("more failing tests", verify.failure_excerpt(text))


@unittest.skipUnless(shutil.which("node") and shutil.which("npm"), "node/npm not installed")
class RealNodeTestFailureTests(TmpDirCase):
    def test_assertion_is_visible_for_a_failing_node_test(self):
        write(self.root, "package.json", json.dumps(
            {"name": "t", "version": "1.0.0", "scripts": {"test": "node --test --test-reporter=tap"}}))
        write(self.root, "a.test.js",
              "const t=require('node:test');const assert=require('node:assert');\n"
              + "".join(f"t.test('ok{i}',()=>{{}});\n" for i in range(60))
              + "t.test('ledger',()=>{assert.strictEqual(18,10)});\n")
        res = run("verify.py", self.root, "--skip", "install", "--timeout", "60")
        self.assertEqual(res.returncode, 1)
        report = (self.root / ".verify" / "VERIFICATION.md").read_text()
        self.assertIn("[failing tests]", report)
        self.assertIn("ledger", report.split("[end of output]")[0])


class WorkspaceProjectFilterTests(TmpDirCase):
    @unittest.skipUnless(shutil.which("npm"), "npm not installed")
    def test_project_flag_still_installs_at_workspace_root(self):
        write(self.root, "package.json", json.dumps({"name": "root", "private": True, "workspaces": ["packages/*"]}))
        hook = "node -e \"require('fs').writeFileSync('installed.txt','x')\""
        write(self.root, "packages/a/package.json",
              json.dumps({"name": "a", "version": "1.0.0", "scripts": {"build": "node -e \"1\""}}))
        write(self.root, "package.json", json.dumps(
            {"name": "root", "private": True, "workspaces": ["packages/*"], "scripts": {"postinstall": hook}}))
        res = run("verify.py", self.root, "--project", "packages/a", "--timeout", "120")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("install", res.stdout)
        self.assertTrue((self.root / "installed.txt").exists(), "root install did not run")


if __name__ == "__main__":
    unittest.main()
