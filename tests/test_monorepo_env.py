"""Tests for monorepo support and safe environment variables."""
import json
import shutil
import sys
import unittest
from pathlib import Path

from test_scripts import SCRIPTS, TmpDirCase, free_port, run, write  # noqa: F401

sys.path.insert(0, str(SCRIPTS))

import detect_checks  # noqa: E402
import envutil  # noqa: E402
import verify  # noqa: E402


def pkg(**fields) -> str:
    return json.dumps({"name": fields.pop("name", "x"), "version": "1.0.0", **fields})


# --------------------------------------------------------------- detection
class MonorepoDetectTests(TmpDirCase):
    def steps(self, only=None):
        return [(s["kind"], s["cwd"]) for s in detect_checks.detect(self.root, only)]

    def make_workspace(self, root_scripts=None):
        write(self.root, "package.json", pkg(name="root", workspaces=["apps/*"], scripts=root_scripts or {}))
        write(self.root, "apps/web/package.json",
              pkg(name="@acme/web", scripts={"build": "x", "test": "y"}, devDependencies={"typescript": "5"}))
        write(self.root, "apps/web/tsconfig.json", "{}")
        write(self.root, "apps/api/package.json", pkg(name="@acme/api", scripts={"test": "y"}))

    def test_workspace_installs_once_at_root(self):
        self.make_workspace()
        steps = self.steps()
        self.assertEqual([s for s in steps if s[0] == "install"], [("install", ".")])
        self.assertIn(("build", "apps/web"), steps)
        self.assertIn(("test", "apps/web"), steps)
        self.assertIn(("test", "apps/api"), steps)
        self.assertIn(("typecheck", "apps/web"), steps)
        self.assertEqual(steps[0], ("install", "."))

    def test_root_build_is_not_repeated_in_children(self):
        self.make_workspace(root_scripts={"build": "turbo run build"})
        steps = self.steps()
        self.assertIn(("build", "."), steps)
        self.assertNotIn(("build", "apps/web"), steps)
        self.assertIn(("test", "apps/web"), steps)  # root has no test, so children keep theirs

    def test_independent_apps_each_get_an_install(self):
        write(self.root, "web/package.json", pkg(scripts={"build": "x"}))
        write(self.root, "admin/package.json", pkg(scripts={"build": "x"}))
        installs = [cwd for kind, cwd in self.steps() if kind == "install"]
        self.assertEqual(sorted(installs), ["admin", "web"])

    def test_project_filter_keeps_workspace_root_install(self):
        self.make_workspace()
        only = self.steps(["apps/web"])
        self.assertEqual(only[0], ("install", "."))
        self.assertIn(("build", "apps/web"), only)
        self.assertNotIn(("test", "apps/api"), only)

    def test_project_filter_without_workspace_adds_no_root_install(self):
        write(self.root, "web/package.json", pkg(scripts={"build": "x"}))
        write(self.root, "admin/package.json", pkg(scripts={"build": "x"}))
        self.assertEqual([c for k, c in self.steps(["web"]) if k == "install"], ["web"])

    def test_pnpm_workspace_file_selects_pnpm(self):
        write(self.root, "package.json", pkg(scripts={"build": "x"}))
        write(self.root, "pnpm-workspace.yaml", "packages:\n  - 'apps/*'\n")
        cmds = [s["cmd"] for s in detect_checks.detect(self.root)]
        self.assertIn("pnpm install", cmds)
        self.assertIn("pnpm run build", cmds)

    def test_mixed_stack_and_filters(self):
        write(self.root, "package.json", pkg(scripts={"build": "x"}))
        write(self.root, "backend/requirements.txt", "requests\n")
        write(self.root, "backend/tests/test_a.py", "")
        steps = self.steps()
        self.assertIn(("install", "."), steps)
        self.assertIn(("install", "backend"), steps)
        self.assertIn(("test", "backend"), steps)
        only = self.steps(["backend"])
        self.assertTrue(only and all(cwd == "backend" for _, cwd in only))

    def test_ignores_dependency_folders_and_deep_nesting(self):
        write(self.root, "package.json", pkg(scripts={"build": "x"}))
        write(self.root, "node_modules/dep/package.json", pkg(scripts={"build": "x"}))
        write(self.root, "a/b/c/d/package.json", pkg(scripts={"build": "x"}))
        cwds = {cwd for _, cwd in self.steps()}
        self.assertEqual(cwds, {"."})


# ---------------------------------------------------------- check_imports
class MonorepoImportTests(TmpDirCase):
    def test_hoisting_and_workspace_packages(self):
        write(self.root, "package.json", pkg(name="root", workspaces=["apps/*", "packages/*"],
                                             devDependencies={"zod": "3"}))
        write(self.root, "apps/web/package.json", pkg(name="@acme/web", dependencies={"next": "14"}))
        write(self.root, "packages/ui/package.json", pkg(name="@acme/ui", dependencies={"clsx": "2"}))
        write(self.root, "apps/web/page.tsx",
              "import n from 'next';\nimport z from 'zod';\nimport u from '@acme/ui';\nimport l from 'lodash';\n")
        write(self.root, "packages/ui/button.tsx", "import c from 'clsx';\nimport n from 'next';\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 1)
        out = res.stdout
        self.assertIn("apps/web/page.tsx:4 imports 'lodash' but it is not in apps/web/package.json", out)
        self.assertIn("packages/ui/button.tsx:2 imports 'next' but it is not in packages/ui/package.json", out)
        for ok in ("imports 'zod'", "imports '@acme/ui'", "imports 'clsx'"):
            self.assertNotIn(ok, out)
        self.assertNotIn("page.tsx:1", out)

    def test_python_services_with_own_requirements(self):
        write(self.root, "api/requirements.txt", "fastapi\n")
        write(self.root, "worker/requirements.txt", "celery\n")
        write(self.root, "api/main.py", "import fastapi\nimport celery\nimport pandas\n")
        res = run("check_imports.py", self.root)
        self.assertEqual(res.returncode, 1)
        self.assertIn("'pandas'", res.stdout)
        self.assertNotIn("'fastapi'", res.stdout)
        self.assertNotIn("'celery'", res.stdout)


# --------------------------------------------------------------------- env
class EnvTests(TmpDirCase):
    def test_env_file_parsing(self):
        f = write(self.root, ".env.example",
                  "# comment\n\nNEXT_PUBLIC_URL=https://example.test\nexport KEY2='quoted value'\nKEY3=\"dq\"\nbroken line\n")
        self.assertEqual(envutil.parse_env_file(f),
                         {"NEXT_PUBLIC_URL": "https://example.test", "KEY2": "quoted value", "KEY3": "dq"})

    def test_explicit_pairs_override_file(self):
        f = write(self.root, "e", "A=1\nB=2\n")
        self.assertEqual(envutil.collect(str(f), ["B=3"]), {"A": "1", "B": "3"})

    def test_dangerous_variables_are_refused(self):
        for key in ("PATH", "NODE_OPTIONS", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "PYTHONPATH",
                    "NPM_CONFIG_REGISTRY", "pip_index_url", "BASH_ENV"):
            with self.assertRaises(envutil.EnvError, msg=key):
                envutil.parse_pairs([f"{key}=x"])
        write(self.root, ".env.example", "NODE_OPTIONS=--require ./evil.js\n")
        with self.assertRaises(envutil.EnvError):
            envutil.parse_env_file(self.root / ".env.example")

    def test_invalid_names_and_syntax(self):
        for bad in ("1ABC=x", "A B=x", "novalue"):
            with self.assertRaises(envutil.EnvError, msg=bad):
                envutil.parse_pairs([bad])

    def test_verify_cli_refuses_dangerous_env(self):
        write(self.root, "package.json", pkg(scripts={"build": "x"}))
        res = run("verify.py", self.root, "--env", "NODE_OPTIONS=--require=x")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("refusing to set NODE_OPTIONS", res.stderr + res.stdout)

    def test_steps_receive_env_and_report_hides_values(self):
        py = sys.executable
        step = {"kind": "build", "stack": "x", "cwd": ".",
                "cmd": f"\"{py}\" -c \"import os,sys; sys.exit(0 if os.environ.get('MY_FLAG')=='on' else 9)\""}
        self.assertEqual(verify.run_step(step, self.root, 30, {"MY_FLAG": "on"})["status"], "passed")
        self.assertEqual(verify.run_step(step, self.root, 30, {})["exit_code"], 9)

    def test_smoke_test_passes_env_to_app(self):
        server = write(self.root, "server.py",
                       "import http.server, os\n"
                       "class H(http.server.BaseHTTPRequestHandler):\n"
                       "    def do_GET(self):\n"
                       "        self.send_response(200 if os.environ.get('MY_FLAG') == 'on' else 503)\n"
                       "        self.end_headers()\n"
                       "    def log_message(self, *a): pass\n"
                       "import socketserver\n"
                       "class S(http.server.HTTPServer):\n"
                       "    def server_bind(self):\n"
                       "        # skip socket.getfqdn(): its reverse lookup can hang ~30s on macOS CI runners\n"
                       "        socketserver.TCPServer.server_bind(self)\n"
                       "        self.server_name, self.server_port = 'localhost', self.server_address[1]\n"
                       "S(('127.0.0.1', int(os.environ['PORT'])), H).serve_forever()\n")
        cmd = f'"{sys.executable}" {server.name}'
        port = free_port()
        good = run("smoke_test.py", "--cwd", self.root, "--cmd", cmd, "--port", port,
                   "--expect", "200", "--env", "MY_FLAG=on", "--timeout", "20")
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        bad = run("smoke_test.py", "--cwd", self.root, "--cmd", cmd, "--port", free_port(),
                  "--expect", "200", "--timeout", "20")
        self.assertEqual(bad.returncode, 1)


# ------------------------------------------------------ verify in monorepos
@unittest.skipUnless(shutil.which("npm"), "npm not installed")
class MonorepoVerifyTests(TmpDirCase):
    def make(self):
        write(self.root, "package.json", pkg(name="root", workspaces=["packages/*"]))
        build = "node -e \"require('fs').writeFileSync('built.txt','ok')\""
        write(self.root, "packages/a/package.json", pkg(name="a", scripts={"build": build}))
        write(self.root, "packages/b/package.json", pkg(name="b", scripts={"build": build}))

    def test_runs_each_step_in_its_own_directory(self):
        self.make()
        res = run("verify.py", self.root, "--timeout", "180")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertTrue((self.root / "packages/a/built.txt").exists())
        self.assertTrue((self.root / "packages/b/built.txt").exists())
        self.assertFalse((self.root / "built.txt").exists())
        report = (self.root / ".verify" / "VERIFICATION.md").read_text()
        self.assertIn("`packages/a`", report)

    def test_project_filter(self):
        self.make()
        res = run("verify.py", self.root, "--project", "packages/a", "--skip", "install", "--timeout", "120")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertTrue((self.root / "packages/a/built.txt").exists())
        self.assertFalse((self.root / "packages/b/built.txt").exists())


if __name__ == "__main__":
    unittest.main()
