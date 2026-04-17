"""M5 — firejail subprocess isolation.

Role: run agent-driven commands (pytest, formatters, scripts) inside a
firejail profile. No network by default. Refuses cwd outside
`.hypha/worktrees/`. Fails loudly when firejail is missing rather than
silently falling back to plain subprocess — the thesis relies on real
isolation.
Produces: subprocess results.
Consumes: command + cwd + profile.

The default profile ships at hypha/sandbox/hypha.profile and is also the
baseline argument set; callers may point at a more restrictive custom
profile.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROFILE = Path(__file__).resolve().parent / "hypha.profile"
WORKTREE_PREFIX_PARTS = (".hypha", "worktrees")


@dataclass
class Result:
    rc: int
    stdout: str
    stderr: str
    ms: int


class FirejailError(RuntimeError):
    pass


def _is_under_worktrees(cwd: Path) -> bool:
    parts = cwd.resolve().parts
    for i in range(len(parts) - 1):
        if (parts[i], parts[i + 1]) == WORKTREE_PREFIX_PARTS:
            return True
    return False


def _ensure_installed() -> str:
    bin_ = shutil.which("firejail")
    if bin_ is None:
        raise FirejailError(
            "firejail is not installed; M5 requires real sandbox isolation. "
            "Install firejail (apt/pacman/brew) or run the loop with M3 "
            "semantics before enabling M5."
        )
    return bin_


def _timeout_hms(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_argv(
    firejail_bin: str,
    profile: Path,
    cwd: Path,
    argv: list[str],
    timeout: int,
) -> list[str]:
    return [
        firejail_bin,
        "--quiet",
        f"--profile={profile}",
        "--net=none",
        "--private-cwd",
        f"--whitelist={cwd.resolve()}",
        f"--timeout={_timeout_hms(timeout)}",
        "--",
        *argv,
    ]


class Firejail:
    def __init__(self, profile: Path = DEFAULT_PROFILE):
        self.profile = Path(profile).expanduser().resolve()
        if not self.profile.exists():
            raise FirejailError(f"profile not found: {self.profile}")

    async def run(self, argv: list[str], cwd: Path, timeout: int = 120) -> Result:
        cwd = Path(cwd).expanduser().resolve()
        if not _is_under_worktrees(cwd):
            raise FirejailError(
                f"cwd must be under a .hypha/worktrees/ subtree: {cwd}"
            )
        firejail_bin = _ensure_installed()
        full = build_argv(firejail_bin, self.profile, cwd, argv, timeout)
        t0 = time.perf_counter()
        proc = await asyncio.to_thread(
            subprocess.run, full, cwd=str(cwd), capture_output=True, text=True, check=False
        )
        ms = int((time.perf_counter() - t0) * 1000)
        return Result(
            rc=proc.returncode,
            stdout=proc.stdout[-4000:],
            stderr=proc.stderr[-4000:],
            ms=ms,
        )
