"""Tests for the verified-code-delivery scripts. Standard library only.

Run:  python -m unittest discover -s tests -v

Fake secrets are assembled at runtime from fragments so that this repository
never contains a literal secret-looking string (the repo scans itself in CI).
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "verified-code-delivery" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import changed_files  # noqa: E402
import detect_checks  # noqa: E402
import secret_scan  # noqa: E402
import verify  # noqa: E402


def run(script: str, *args: str, cwd: Path | None = None, timeout: int = 120):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


def write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def fake_jwt(role: str) -> str:
    def enc(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return enc({"alg": "HS256"}) + "." + enc({"role": role, "iss": "supabase"}) + ".abcdefghijklmnop1234567890"


def make_symlink(link: Path, target: Path) -> None:
    """Create a symlink, or skip the test where the OS forbids it (Windows without Developer Mode)."""
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as e:
        raise unittest.SkipTest(f"cannot create symlinks here: {e}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TmpDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)


# --------------------------------------------------------------- secret_scan
class SecretScanTests(TmpDirCase):
    def test_flags_real_looking_secrets(self):
        write(self.root, "a.ts",
              "const k = 'rzp_live_" + "A1b2C3d4E5f6G7" + "';\n"
              "const client_secret = \"" + "Zk9xQw2LmN8vTy4RpS6u" + "\";\n"
              "const s = '" + fake_jwt("service_role") + "';\n")
        kinds = {f["kind"] for f in secret_scan.scan_paths([self.root])}
        self.assertIn("Razorpay live key", kinds)
        self.assertIn("hardcoded client_secret", kinds)
        self.assertIn("Supabase service_role key", kinds)

    def test_ignores_safe_content(self):
        write(self.root, "ok.ts",
              "const anon = '" + fake_jwt("anon") + "';\n"
              "const apiKey = process.env.API_KEY;\n"
              "const password = 'your-password-here-please';\n")
        write(self.root, ".env.example", "SECRET=your-secret-here\n")
        write(self.root, "package-lock.json", '{"integrity": "sha512-' + "A" * 80 + '"}')
        self.assertEqual(secret_scan.scan_paths([self.root]), [])

    def test_flags_env_file_and_masks_values(self):
        write(self.root, ".env", "SECRET=abc\n")
        write(self.root, "k.py", 'token = "' + "Qw3rTy9uIo1pAs5dFg7h" + '"\n')
        findings = secret_scan.scan_paths([self.root])
        self.assertTrue(any(f["file"] == ".env" for f in findings))
        for f in findings:
            self.assertNotIn("Qw3rTy9uIo1pAs5dFg7h", f["preview"])

    def test_symlink_is_not_followed(self):
        outside = write(self.root, "outside/secret.txt", "password = '" + "Zk9xQw2LmN8vTy4RpS6u" + "'\n")
        proj = self.root / "proj"
        proj.mkdir()
        make_symlink(proj / "link.txt", outside)
        self.assertEqual(secret_scan.scan_paths([proj]), [])


# ------------------------------------------------------------- check_imports
class CheckImportsTests(TmpDirCase):
    def test_node_missing_import(self):
        write(self.root, "package.json", json.dumps({"name": "t", "dependencies": {"zod": "3"}}))
        write(self.root, "tsconfig.json", '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}')
        write(self.root, "src/a.ts",
              "import path from 'path';\nimport fs from 'node:fs';\nimport z from 'zod';\n"
              "import q from '@/lib/q';\nimport r from './r';\nimport _ from 'lodash';\n"
              "import s from '@scope/pkg/deep';\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("'lodash'", res.stdout)
        self.assertIn("'@scope/pkg'", res.stdout)
        for ok in ("'zod'", "'path'", "'fs'", "'@/lib/q'"):
            self.assertNotIn(ok, res.stdout)

    def test_node_all_declared_passes(self):
        write(self.root, "package.json", json.dumps({"name": "t", "devDependencies": {"vitest": "1"}}))
        write(self.root, "a.test.ts", "import { it } from 'vitest';\n")
        self.assertEqual(run("check_imports.py", self.root).returncode, 0)

    def test_python_missing_and_mapped_imports(self):
        write(self.root, "requirements.txt", "requests==2.31\nPyYAML>=6\n")
        write(self.root, "app/__init__.py")
        write(self.root, "app/util.py", "def f(): pass\n")
        write(self.root, "main.py",
              "import os, requests, yaml\nimport numpy\nfrom app.util import f\nfrom PIL import Image\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("'numpy'", res.stdout)
        self.assertIn("'PIL'", res.stdout)
        for ok in ("'requests'", "'yaml'", "'app'", "'os'"):
            self.assertNotIn(ok, res.stdout)

    def test_python_without_manifest_only_notes(self):
        write(self.root, "main.py", "import numpy\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 0)
        self.assertIn("NOTE", res.stdout)


# ------------------------------------------------------------ changed_files
class ChangedFilesTests(TmpDirCase):
    def test_diff_new_modified_deleted_and_ignores(self):
        write(self.root, "keep.txt", "1")
        write(self.root, "edit.txt", "1")
        write(self.root, "gone.txt", "1")
        snap = changed_files.take_snapshot(self.root)

        write(self.root, "edit.txt", "2")
        write(self.root, "new/file.ts", "x")
        (self.root / "gone.txt").unlink()
        write(self.root, "node_modules/x/i.js", "x")
        write(self.root, ".next/c.js", "x")
        write(self.root, "next-env.d.ts", "x")
        write(self.root, "package-lock.json", "{}")
        write(self.root, ".verify/VERIFICATION.md", "x")

        d = changed_files.diff(self.root, snap)
        self.assertEqual(d["new"], ["new/file.ts"])
        self.assertEqual(d["modified"], ["edit.txt"])
        self.assertEqual(d["deleted"], ["gone.txt"])

    def test_lockfiles_can_be_included(self):
        snap = changed_files.take_snapshot(self.root, include_lockfiles=True)
        write(self.root, "package-lock.json", "{}")
        d = changed_files.diff(self.root, snap, include_lockfiles=True)
        self.assertEqual(d["new"], ["package-lock.json"])

    def test_symlinks_are_ignored(self):
        outside = write(self.root, "outside/o.txt", "x")
        proj = self.root / "proj"
        proj.mkdir()
        make_symlink(proj / "link.txt", outside)
        self.assertEqual(changed_files.take_snapshot(proj), {})


# ---------------------------------------------------------------- make_zip
class MakeZipTests(TmpDirCase):
    def snapshot(self, proj: Path) -> Path:
        snap = self.root / "snap.json"
        self.assertEqual(run("changed_files.py", "snapshot", proj, "--out", snap).returncode, 0)
        return snap

    def test_zip_since_keeps_paths_and_only_changes(self):
        proj = self.root / "proj"
        write(proj, "same.ts", "1")
        write(proj, "src/app/page.tsx", "1")
        snap = self.snapshot(proj)
        write(proj, "src/app/page.tsx", "2")
        write(proj, "src/lib/new.ts", "3")
        out = self.root / "out" / "c.zip"
        res = run("make_zip.py", "--root", proj, "--out", out, "--since", snap)
        self.assertEqual(res.returncode, 0, res.stderr)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(sorted(z.namelist()), ["src/app/page.tsx", "src/lib/new.ts"])

    def test_blocks_when_secret_present(self):
        proj = self.root / "proj"
        write(proj, "bad.ts", "const key = 'rzp_live_" + "A1b2C3d4E5f6G7" + "';\n")
        out = self.root / "x.zip"
        res = run("make_zip.py", "--root", proj, "--out", out, "bad.ts")
        self.assertEqual(res.returncode, 2)
        self.assertFalse(out.exists())
        self.assertNotIn("A1b2C3d4E5f6G7", res.stdout + res.stderr)

    def test_refuses_symlink_and_outside_paths(self):
        proj = self.root / "proj"
        write(proj, "a.txt", "1")
        outside = write(self.root, "outside.txt", "secret stuff")
        make_symlink(proj / "link.txt", outside)
        out = self.root / "x.zip"
        self.assertNotEqual(run("make_zip.py", "--root", proj, "--out", out, "link.txt").returncode, 0)
        self.assertNotEqual(run("make_zip.py", "--root", proj, "--out", out, "../outside.txt").returncode, 0)
        self.assertFalse(out.exists())

    def test_exclude_glob(self):
        proj = self.root / "proj"
        write(proj, "a.ts", "1")
        write(proj, "tsconfig.json", "{}")
        out = self.root / "x.zip"
        res = run("make_zip.py", "--root", proj, "--out", out, "--exclude", "tsconfig.json", "a.ts", "tsconfig.json")
        self.assertEqual(res.returncode, 0, res.stderr)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(z.namelist(), ["a.ts"])


# ----------------------------------------------------------- detect_checks
class DetectChecksTests(TmpDirCase):
    def kinds(self):
        return [(s["kind"], s["cmd"]) for s in detect_checks.detect(self.root)]

    def test_node_steps_and_placeholder_test_script(self):
        write(self.root, "package.json", json.dumps({
            "scripts": {"build": "x", "lint": "y", "test": "echo \"Error: no test specified\" && exit 1"},
            "devDependencies": {"typescript": "5"}}))
        write(self.root, "tsconfig.json", "{}")
        got = self.kinds()
        self.assertEqual([k for k, _ in got], ["install", "typecheck", "lint", "build"])

    def test_tsc_step_requires_typescript_dependency(self):
        write(self.root, "package.json", json.dumps({"scripts": {"build": "x"}}))
        write(self.root, "tsconfig.json", "{}")
        self.assertNotIn("typecheck", [k for k, _ in self.kinds()])

    def test_package_manager_from_lockfile(self):
        write(self.root, "package.json", json.dumps({"scripts": {"build": "x"}}))
        write(self.root, "pnpm-lock.yaml", "")
        self.assertEqual(self.kinds()[0], ("install", "pnpm install"))

    def test_python_steps(self):
        write(self.root, "requirements.txt", "requests\n")
        write(self.root, "tests/test_a.py", "")
        kinds = [k for k, _ in self.kinds()]
        self.assertEqual(kinds, ["install", "typecheck", "test"])


# ------------------------------------------------------------------ verify
class VerifyTests(TmpDirCase):
    def test_run_step_pass_fail_timeout(self):
        py = sys.executable
        ok = verify.run_step({"kind": "build", "cmd": f'"{py}" -c "print(1)"', "stack": "x"}, self.root, 30)
        bad = verify.run_step({"kind": "test", "cmd": f'"{py}" -c "import sys; print(\'boom\'); sys.exit(3)"', "stack": "x"}, self.root, 30)
        slow = verify.run_step({"kind": "test", "cmd": f'"{py}" -c "import time; time.sleep(5)"', "stack": "x"}, self.root, 1)
        self.assertEqual((ok["status"], ok["exit_code"]), ("passed", 0))
        self.assertEqual((bad["status"], bad["exit_code"]), ("failed", 3))
        self.assertIn("boom", bad["tail"])
        self.assertEqual(slow["status"], "timeout")

    @unittest.skipUnless(shutil.which("npm"), "npm not installed")
    def test_ignore_scripts_blocks_install_hooks(self):
        marker = "hook-ran.txt"
        hook = f"node -e \"require('fs').writeFileSync('{marker}','x')\""
        pkg = {"name": "t", "version": "1.0.0", "scripts": {"postinstall": hook, "build": "node -e \"1\""}}

        safe = self.root / "safe"
        write(safe, "package.json", json.dumps(pkg))
        self.assertEqual(run("verify.py", safe, "--ignore-scripts", "--timeout", "120").returncode, 0)
        self.assertFalse((safe / marker).exists(), "install hook ran despite --ignore-scripts")

        normal = self.root / "normal"
        write(normal, "package.json", json.dumps(pkg))
        self.assertEqual(run("verify.py", normal, "--timeout", "120").returncode, 0)
        self.assertTrue((normal / marker).exists())
        self.assertTrue((normal / ".verify" / "VERIFICATION.md").exists())

    @unittest.skipUnless(shutil.which("npm"), "npm not installed")
    def test_failure_is_reported_and_exit_nonzero(self):
        write(self.root, "package.json", json.dumps(
            {"name": "t", "version": "1.0.0", "scripts": {"build": "node -e \"process.exit(4)\""}}))
        res = run("verify.py", self.root, "--timeout", "120")
        self.assertEqual(res.returncode, 1)
        self.assertIn("FAILED", res.stdout)
        report = (self.root / ".verify" / "VERIFICATION.md").read_text()
        self.assertIn("FAIL", report)


# -------------------------------------------------------------- smoke_test
class SmokeTestTests(TmpDirCase):
    def serve_cmd(self, port: int, status: int = 200) -> str:
        server = self.root / "server.py"
        server.write_text(
            "import http.server, sys\n"
            "class H(http.server.BaseHTTPRequestHandler):\n"
            "    def do_GET(self):\n"
            f"        self.send_response({status}); self.end_headers(); self.wfile.write(b'ok')\n"
            "    def log_message(self, *a): pass\n"
            "import socketserver\n"
            "class S(http.server.HTTPServer):\n"
            "    def server_bind(self):\n"
            "        # skip socket.getfqdn(): its reverse lookup can hang ~30s on macOS CI runners\n"
            "        socketserver.TCPServer.server_bind(self)\n"
            "        self.server_name, self.server_port = 'localhost', self.server_address[1]\n"
            f"S(('127.0.0.1', {port}), H).serve_forever()\n",
            encoding="utf-8")
        return f'"{sys.executable}" server.py'

    def test_pass_when_app_responds(self):
        port = free_port()
        res = run("smoke_test.py", "--cwd", self.root, "--cmd", self.serve_cmd(port),
                  "--port", port, "--path", "/", "--expect", "200", "--timeout", "20")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("PASS  GET / -> 200", res.stdout)

    def test_fail_on_500(self):
        port = free_port()
        res = run("smoke_test.py", "--cwd", self.root, "--cmd", self.serve_cmd(port, 500),
                  "--port", port, "--timeout", "20")
        self.assertEqual(res.returncode, 1)
        self.assertIn("-> 500", res.stdout)

    def test_fail_when_app_crashes_on_start(self):
        port = free_port()
        res = run("smoke_test.py", "--cwd", self.root, "--cmd", f'"{sys.executable}" -c "raise SystemExit(1)"',
                  "--port", port, "--timeout", "10")
        self.assertEqual(res.returncode, 1)
        self.assertIn("exited before listening", res.stdout)

    def test_rejects_non_local_paths(self):
        port = free_port()
        for bad in ("http://evil.example/x", "//evil.example/x", "no-slash"):
            res = run("smoke_test.py", "--cwd", self.root, "--cmd", "true", "--port", port, "--path", bad)
            self.assertNotEqual(res.returncode, 0, bad)
            self.assertIn("--path must start", res.stderr)


if __name__ == "__main__":
    unittest.main()
