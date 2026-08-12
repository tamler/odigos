"""Auto-update: check for new code, apply, and restart."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _run_git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    """Run a git command, return (returncode, stdout)."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd or os.getcwd(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode, result.stdout.strip()


def is_git_repo() -> bool:
    """Check if the current working directory is a git repo."""
    code, _ = _run_git("rev-parse", "--is-inside-work-tree")
    return code == 0


def check_for_updates(branch: str = "main") -> dict | None:
    """Check if remote has new commits.

    Returns info dict or None if up to date.
    """
    if not is_git_repo():
        return None

    # Fetch latest from remote
    code, _ = _run_git("fetch", "origin", branch)
    if code != 0:
        logger.warning("git fetch failed")
        return None

    # Compare local HEAD with remote
    code, local_hash = _run_git("rev-parse", "HEAD")
    if code != 0:
        return None
    _, remote_hash = _run_git("rev-parse", f"origin/{branch}")
    if local_hash == remote_hash:
        return None

    # Get commit log of what's new
    _, log_output = _run_git(
        "log", "--oneline", f"HEAD..origin/{branch}",
    )
    commit_count = (
        len(log_output.strip().splitlines())
        if log_output.strip()
        else 0
    )

    return {
        "local": local_hash[:8],
        "remote": remote_hash[:8],
        "commits": commit_count,
        "log": log_output[:500],
    }


def apply_update(branch: str = "main") -> tuple[bool, str]:
    """Pull latest code and rebuild dashboard if needed.

    Returns (success, message).
    """
    # Pull latest
    code, output = _run_git("pull", "origin", branch)
    if code != 0:
        return False, f"git pull failed: {output}"

    # Check if dashboard needs rebuilding
    _, diff_output = _run_git(
        "diff", "--name-only", "HEAD~1..HEAD",
    )
    needs_dashboard_rebuild = any(
        line.startswith("dashboard/")
        for line in diff_output.splitlines()
        if line.strip()
    )

    if needs_dashboard_rebuild:
        dashboard_dir = Path("dashboard")
        if dashboard_dir.exists():
            logger.info("Dashboard files changed, rebuilding...")
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(dashboard_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.error(
                    "Dashboard build failed: %s",
                    result.stderr[-500:],
                )
                return (
                    False,
                    f"Dashboard build failed: "
                    f"{result.stderr[-200:]}",
                )

    return True, output


def _own_systemd_unit() -> str | None:
    """Return the systemd unit owning this process, or None.

    Read from the cgroup rather than guessed from a list of known service
    names: installs get added, renamed and retired, and a hardcoded list
    silently stops matching, which downgrades every self-update to a bare
    re-exec that leaves the unit's hardening behind.
    """
    try:
        content = Path("/proc/self/cgroup").read_text()
    except OSError:
        return None
    match = re.search(r"/([A-Za-z0-9@_.\-]+\.service)", content)
    return match.group(1) if match else None


def restart_service() -> None:
    """Restart the running service.

    Works for both systemd and Docker.
    """
    pid = os.getpid()

    service_name = _own_systemd_unit()
    if service_name:
        # Confirm the unit really owns us before handing it our lifecycle.
        status = subprocess.run(
            [
                "systemctl", "show", service_name,
                "--property=MainPID",
            ],
            capture_output=True,
            text=True,
        )
        if f"MainPID={pid}" in status.stdout:
            logger.info(
                "Restarting via systemd: %s", service_name,
            )
            os.execvp(
                "systemctl",
                ["systemctl", "restart", service_name],
            )
            return  # won't reach here

    # Fallback: just re-exec ourselves
    logger.info("Restarting via exec: %s", sys.argv)
    os.execv(sys.executable, [sys.executable] + sys.argv)
