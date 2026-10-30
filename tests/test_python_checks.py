"""Tests for: compileall ignoring dependency folders, and a missing `python -m tool` reported as MISSING TOOL."""
import sys
import unittest

from test_scripts import SCRIPTS, TmpDirCase, run, write

sys.path.insert(0, str(SCRIPTS))

import detect_checks  # noqa: E402
import verify  # noqa: E402


class CompileallScopeTests(TmpDirCase):
    def typecheck(self, *extra):
        return run("verify.py", self.root, "--only", "typecheck", "--out", self.root / "_out", *extra)

    def test_foreign_python_files_in_dependency_folders_do_not_fail_the_check(self):
        write(self.root, "requirements.txt", "requests\n")
        write(self.root, "main.py", "print('ok')\n")
        write(self.root, "node_modules/node-gyp/gyp/old.py", "print 'python 2'\n")
        write(self.root, ".venv/lib/site-packages/pkg/bad.py", "def f(:\n")
        write(self.root, "web/node_modules/x/bad.py", "def f(:\n")
        res = self.typecheck()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_a_real_syntax_error_in_project_code_still_fails(self):
        write(self.root, "requirements.txt", "requests\n")
        write(self.root, "app/broken.py", "def f(:\n")
        write(self.root, "node_modules/x/bad.py", "def f(:\n")
        res = self.typecheck()
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("broken.py", res.stdout)

    def test_similar_folder_names_are_not_skipped(self):
        write(self.root, "requirements.txt", "requests\n")
        write(self.root, "convenv/broken.py", "def f(:\n")   # contains 'venv' but is not a venv
        write(self.root, "rebuilder/broken.py", "def f(:\n")  # contains 'build' but is not build/
        self.assertEqual(self.typecheck().returncode, 1)


class MissingPythonModuleTests(TmpDirCase):
    def step(self, cmd):
        return verify.run_step({"kind": "test", "stack": "python", "cwd": ".", "cmd": cmd}, self.root, 30)

    def test_tool_module_not_installed_is_missing_not_failed(self):
        r = self.step(f'"{sys.executable}" -m definitely_not_installed_xyz -q')
        self.assertEqual(r["status"], "missing")

    def test_a_failing_test_run_is_still_a_failure(self):
        r = self.step(f'"{sys.executable}" -c "import sys; print(\'1 failed\'); sys.exit(1)"')
        self.assertEqual(r["status"], "failed")

    def test_import_error_inside_the_code_is_still_a_failure(self):
        write(self.root, "t.py", "import some_missing_dependency_xyz\n")
        r = self.step(f'"{sys.executable}" -m t')
        self.assertEqual(r["status"], "failed")  # t exists, a module it imports does not


if __name__ == "__main__":
    unittest.main()
