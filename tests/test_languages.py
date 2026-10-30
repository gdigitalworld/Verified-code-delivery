"""Tests for the extra stacks and the syntax-check fallback for plain files."""
import json
import sys
import unittest

from test_scripts import SCRIPTS, TmpDirCase, run, write

sys.path.insert(0, str(SCRIPTS))

import detect_checks  # noqa: E402


class OtherStackTests(TmpDirCase):
    def got(self):
        return [(s["stack"], s["kind"], s["cmd"]) for s in detect_checks.detect(self.root)]

    def test_maven_and_wrapper(self):
        write(self.root, "pom.xml", "<project/>")
        self.assertIn(("java/maven", "test", "mvn -B -q test"), self.got())
        write(self.root, "mvnw", "")
        self.assertIn(("java/maven", "test", "./mvnw -B -q test"), self.got())

    def test_gradle(self):
        write(self.root, "build.gradle.kts", "")
        self.assertIn(("java/gradle", "test", "gradle --console=plain -q test"), self.got())

    def test_dotnet_is_found_by_extension(self):
        write(self.root, "App.csproj", "<Project/>")
        self.assertIn(("dotnet", "build", "dotnet build --nologo -v q"), self.got())

    def test_php_composer_test_script(self):
        write(self.root, "composer.json", json.dumps({"scripts": {"test": "phpunit"}}))
        kinds = [(k, c) for _, k, c in self.got()]
        self.assertIn(("install", "composer install --no-interaction"), kinds)
        self.assertIn(("test", "composer test"), kinds)

    def test_ruby_dart_flutter_swift_cmake_deno_elixir(self):
        write(self.root, "r/Gemfile", "")
        write(self.root, "r/spec/a_spec.rb", "")
        write(self.root, "d/pubspec.yaml", "name: x\n")
        write(self.root, "f/pubspec.yaml", "name: x\nflutter:\n  uses-material-design: true\n")
        write(self.root, "s/Package.swift", "")
        write(self.root, "c/CMakeLists.txt", "enable_testing()\n")
        write(self.root, "n/deno.json", "{}")
        write(self.root, "e/mix.exs", "")
        cmds = [c for _, _, c in self.got()]
        for want in ("bundle exec rspec", "dart analyze", "flutter analyze", "swift test",
                     "ctest --test-dir build --output-on-failure", "deno test", "mix test"):
            self.assertIn(want, cmds)

    def test_makefile_used_only_when_nothing_else_covers_the_folder(self):
        write(self.root, "Makefile", "build:\n\techo b\ntest:\n\techo t\n")
        self.assertEqual([c for _, _, c in self.got()], ["make build", "make test"])
        write(self.root, "package.json", json.dumps({"scripts": {"build": "x"}}))
        self.assertFalse(any(c.startswith("make") for _, _, c in self.got()))


class LooseFileTests(TmpDirCase):
    def test_plain_files_get_a_syntax_check_each(self):
        write(self.root, "a.py", "print(1)\n")
        write(self.root, "tool.sh", "echo hi\n")
        write(self.root, "data.json", "{}")
        write(self.root, "notes.txt", "ignored")
        cmds = [s["cmd"] for s in detect_checks.detect(self.root)]
        self.assertEqual(cmds, [f"{detect_checks.PY} -m py_compile a.py", f"{detect_checks.PY} -m json.tool data.json > /dev/null", "bash -n tool.sh"])

    def test_awkward_file_names_cannot_inject_commands(self):
        write(self.root, "x; touch pwned.sh", "echo hi\n")
        res = run("verify.py", self.root)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertFalse((self.root / "pwned.sh").exists())

    def test_syntax_error_is_reported_as_failure(self):
        write(self.root, "bad.py", "def f(:\n")
        res = run("verify.py", self.root)
        self.assertEqual(res.returncode, 1, res.stdout)
        self.assertIn("FAILED", res.stdout)

    def test_project_files_win_over_loose_file_fallback(self):
        write(self.root, "requirements.txt", "requests\n")
        write(self.root, "a.py", "print(1)\n")
        self.assertNotIn("syntax", [s["kind"] for s in detect_checks.detect(self.root)])

    def test_dependency_folders_are_skipped(self):
        write(self.root, "node_modules/x/y.py", "def f(:\n")
        self.assertEqual(detect_checks.detect(self.root), [])


if __name__ == "__main__":
    unittest.main()
