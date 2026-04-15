#!/usr/bin/env bash
# Operator-side helper: pre-provision a single owner account for an Odigos install.
# Writes data/seed_user.json, which the bootstrap consumes on next startup to
# create the user and then deletes the file.
#
# Usage:
#   bash scripts/seed-account.sh <install_dir> <username> <email> <temp_password> [display_name]
#
# Example:
#   bash scripts/seed-account.sh /opt/odigos-honey jacob jacob@example.com 'TempPass123' Jacob
#   systemctl restart odigos-honey
#
# After the agent restarts, the tester can log in with the username + temp
# password and will be forced to change the password on first login (the
# must_change_password flag is set true).

set -euo pipefail

if [ $# -lt 4 ]; then
    cat >&2 <<USAGE
Usage: $0 <install_dir> <username> <email> <temp_password> [display_name]

Example:
  $0 /opt/odigos-honey jacob jacob@example.com TempPass123 Jacob
USAGE
    exit 1
fi

DIR="$1"
USERNAME="$2"
EMAIL="$3"
PASSWORD="$4"
DISPLAY_NAME="${5:-$USERNAME}"

if [ ! -d "$DIR" ]; then
    echo "ERROR: install dir does not exist: $DIR" >&2
    exit 1
fi

# Basic validation — fail fast on obvious mistakes
if [ ${#PASSWORD} -lt 8 ]; then
    echo "ERROR: password must be at least 8 characters" >&2
    exit 1
fi
if ! echo "$EMAIL" | grep -qE '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'; then
    echo "ERROR: invalid email format: $EMAIL" >&2
    exit 1
fi

mkdir -p "$DIR/data"
SEED="$DIR/data/seed_user.json"

# Use python3 for proper JSON escaping (handles quotes / backslashes in any field).
python3 - "$USERNAME" "$EMAIL" "$PASSWORD" "$DISPLAY_NAME" "$SEED" <<'PY'
import json, sys
username, email, password, display_name, path = sys.argv[1:6]
payload = {
    "username": username,
    "email": email,
    "password": password,
    "display_name": display_name,
    "must_change_password": True,
}
with open(path, "w") as f:
    json.dump(payload, f)
PY

# Lock down — contains a plaintext password until bootstrap consumes it
chmod 600 "$SEED"

# Match service user ownership if known (best effort)
if [ -d "$DIR/.venv" ]; then
    OWNER=$(stat -c '%U:%G' "$DIR/.venv" 2>/dev/null || echo "")
    if [ -n "$OWNER" ]; then
        chown "$OWNER" "$SEED" 2>/dev/null || true
    fi
fi

echo "Seeded $SEED"
echo ""
echo "  Username:      $USERNAME"
echo "  Email:         $EMAIL"
echo "  Temp password: $PASSWORD"
echo "  Display name:  $DISPLAY_NAME"
echo ""
echo "Restart the agent service to consume the seed file:"
echo "  systemctl restart \$(basename $DIR | sed 's|^opt/||')   # systemd"
echo "  docker restart \$(basename $DIR)                        # docker"
echo ""
echo "WARNING: $SEED contains a plaintext password until first boot consumes it."
