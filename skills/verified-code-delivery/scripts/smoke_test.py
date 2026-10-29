#!/usr/bin/env python3
"""Start an app for real and hit its endpoints, to catch runtime crashes
that build and tests miss.

Usage:
  python smoke_test.py --cwd <dir> --cmd "<start command>" --port 3000 \
      [--path /] [--path /api/health] [--expect 200] [--timeout 60]
      [--env KEY=VALUE ...] [--env-file .env.example]

--path can be repeated (default "/"). Without --expect, any status below 500
counts as alive (so a 401 or 404 from a protected route is not a failure);
with --expect, the status must match exactly.
The start command gets PORT=<port> in its environment, plus anything from
--env / --env-file (placeholders are fine; variables that change how code is
loaded, such as PATH or NODE_OPTIONS, are refused). Exit code 0 = all passed.
"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import envutil  # noqa: E402


def port_open(port: int) -> bool:
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            continue
    return False


def fetch(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        # No process groups on Windows: with shell=True the app is a child of cmd.exe,
        # so end the whole tree or the app keeps running and locks the log and the folder.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        try:
            proc.wait(timeout=8)
        except Exception:
            pass
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=8)
    except Exception:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cwd", required=True)
    p.add_argument("--cmd", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--path", action="append", default=[])
    p.add_argument("--expect", type=int, default=None)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--env-file", default="")
    args = p.parse_args()
    try:
        extra_env = envutil.collect(args.env_file or None, args.env)
    except envutil.EnvError as e:
        sys.exit(f"ERROR  {e}")
    paths = args.path or ["/"]
    for path in paths:
        if not path.startswith("/") or path.startswith("//"):
            sys.exit(f"--path must start with a single '/': {path!r} (only localhost is ever contacted)")

    if port_open(args.port):
        sys.exit(f"Port {args.port} is already in use. Pick another with --port.")

    log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
    env = dict(os.environ, PORT=str(args.port), NODE_ENV=os.environ.get("NODE_ENV", "production"))
    env.update(extra_env)
    proc = subprocess.Popen(
        args.cmd, shell=True, cwd=args.cwd, env=env,
        stdout=log, stderr=subprocess.STDOUT, **({} if os.name == "nt" else {"start_new_session": True}),
    )

    def tail() -> str:
        log.flush()
        with open(log.name, errors="replace") as f:
            return "".join(f.readlines()[-40:]).strip() or "(no output)"

    failures = 0
    try:
        deadline = time.time() + args.timeout
        while not port_open(args.port):
            if proc.poll() is not None:
                print(f"FAIL  app exited before listening (exit code {proc.returncode})")
                print(tail())
                sys.exit(1)
            if time.time() > deadline:
                print(f"FAIL  nothing listening on port {args.port} after {args.timeout}s")
                print(tail())
                sys.exit(1)
            time.sleep(0.5)
        print(f"OK    app is listening on port {args.port}")

        for path in paths:
            status = fetch(f"http://127.0.0.1:{args.port}{path}")
            good = (status == args.expect) if args.expect else (status < 500)
            print(f"{'PASS' if good else 'FAIL'}  GET {path} -> {status}")
            failures += 0 if good else 1

        if proc.poll() is not None:
            print(f"FAIL  app crashed while serving requests (exit code {proc.returncode})")
            failures += 1
        if failures:
            print("\n--- app log (last lines) ---")
            print(tail())
    finally:
        stop(proc)
        log.close()
        for _ in range(25):  # Windows may release the file a moment after the process ends
            try:
                os.unlink(log.name)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                time.sleep(0.2)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
