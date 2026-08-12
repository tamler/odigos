"""Guards on the deploy.sh install table.

The C0 isolation checklist requires every hosted install to run as its own Unix
user. A shared user means each install can read every sibling's .env, DB and
data dir, which makes the "separate filesystem root per account" boundary
fiction. deploy.sh has a runtime preflight for this; these tests catch a bad
row at commit time instead of at deploy time.
"""
import re
from pathlib import Path

import pytest

DEPLOY_SH = Path(__file__).resolve().parent.parent / "deploy.sh"


def _install_rows() -> list[tuple[str, str, str, str]]:
    """Parse the INSTALLS=( "dir:service:user:branch" ... ) array."""
    text = DEPLOY_SH.read_text()
    block = re.search(r"^INSTALLS=\((.*?)^\)", text, re.S | re.M)
    assert block, "INSTALLS array not found in deploy.sh"
    rows = re.findall(r'"([^"]+)"', block.group(1))
    parsed = []
    for row in rows:
        parts = row.split(":")
        assert len(parts) == 4, f"expected dir:service:user:branch, got {row!r}"
        parsed.append(tuple(parts))
    return parsed


def test_install_table_is_not_empty():
    assert _install_rows(), "deploy.sh has no installs configured"


def test_no_two_installs_share_a_service_user():
    users = [user for _, _, user, _ in _install_rows()]
    dupes = {u for u in users if users.count(u) > 1}
    assert not dupes, (
        f"service user(s) shared across installs: {sorted(dupes)}. "
        "Each install needs its own Unix user or they can read each other's secrets."
    )


def test_no_install_uses_the_legacy_shared_user():
    users = {user for _, _, user, _ in _install_rows()}
    assert "odigos_agent" not in users, (
        "odigos_agent was the shared user that the C0 checklist exists to eliminate"
    )


@pytest.mark.parametrize("field", ["dir", "service", "user"])
def test_install_identifiers_are_unique(field):
    idx = {"dir": 0, "service": 1, "user": 2}[field]
    values = [row[idx] for row in _install_rows()]
    assert len(values) == len(set(values)), f"duplicate {field} in deploy.sh INSTALLS"


def test_deploy_does_not_target_retired_hosts():
    """The old bare-metal and uxrls boxes are decommissioned."""
    text = DEPLOY_SH.read_text()
    for dead in ("82.25.91.86", "100.89.147.103"):
        assert dead not in text, f"deploy.sh still targets retired host {dead}"
