"""Shared helpers for passing environment variables to checks safely.

Builds often need variables such as NEXT_PUBLIC_SUPABASE_URL just to compile.
Pass placeholder values with --env KEY=VALUE or --env-file .env.example.
Variables that can hijack how a process loads code (PATH, LD_PRELOAD,
NODE_OPTIONS, PYTHONPATH, ...) are refused, so a hostile .env.example cannot
change what gets executed. Values are never printed.
"""
import re
from pathlib import Path

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

BLOCKED_EXACT = {
    "PATH", "HOME", "SHELL", "IFS", "ENV", "BASH_ENV", "PS4", "PROMPT_COMMAND",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
    "NODE_OPTIONS", "NODE_PATH", "NODE_EXTRA_CA_CERTS", "NPM_CONFIG_REGISTRY",
    "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
    "GIT_SSH_COMMAND", "GIT_ASKPASS", "RUSTC_WRAPPER", "CARGO_HOME", "GOFLAGS",
}
BLOCKED_PREFIXES = ("DYLD_", "LD_", "NPM_CONFIG_", "PIP_", "YARN_", "COREPACK_")


class EnvError(ValueError):
    pass


def check_key(key: str) -> str:
    if not KEY_RE.match(key):
        raise EnvError(f"invalid environment variable name: {key!r}")
    upper = key.upper()
    if upper in BLOCKED_EXACT or upper.startswith(BLOCKED_PREFIXES):
        raise EnvError(f"refusing to set {key}: it can change how code is loaded or fetched")
    return key


def parse_pairs(pairs: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise EnvError(f"--env expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        env[check_key(key.strip())] = value
    return env


def parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env[check_key(key.strip())] = value
    return env


def collect(env_file: str | None, pairs: list[str]) -> dict[str, str]:
    """Env from a file first, then explicit --env pairs (which win)."""
    env: dict[str, str] = {}
    if env_file:
        path = Path(env_file)
        if not path.is_file():
            raise EnvError(f"env file not found: {env_file}")
        env.update(parse_env_file(path))
    env.update(parse_pairs(pairs))
    return env
