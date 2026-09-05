#!/usr/bin/env bash
# Manage the openpaw MCP server as a systemd *user* service
# (unit: openpaw-mcp.service). No sudo required — everything lives
# under ~/.config/systemd/user and is controlled with `systemctl --user`.
# Usage: ./rund.sh {install|start|stop|status|unit}
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="$(pwd -P)"
UNIT_NAME="openpaw-mcp.service"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="$UNIT_DIR/$UNIT_NAME"
OLD_SYSTEM_UNIT="/etc/systemd/system/$UNIT_NAME"
PYBIN="$REPO_DIR/.venv/bin/python"
SERVER="$REPO_DIR/mcp/openpaw_mcp_server.py"

die() { echo "ERROR: $*" >&2; exit 1; }

require_venv() {
    [ -x "$PYBIN" ] || die ".venv not found — run ./setup.sh first"
}

# The systemd user manager is not always reachable (e.g. plain ssh without
# a dbus session). Fail with something actionable instead of a cryptic
# "Failed to connect to bus".
require_user_manager() {
    if ! systemctl --user show 2>/dev/null >/dev/null; then
        die "systemd user manager is not reachable.
Try: export XDG_RUNTIME_DIR=/run/user/$(id -u)  (or log in locally / use SSH with pam_systemd)."
    fi
}

require_installed() {
    [ -f "$UNIT_FILE" ] || die "$UNIT_NAME is not installed — run ./rund.sh install first"
}

check_old_system_unit() {
    if [ -f "$OLD_SYSTEM_UNIT" ]; then
        echo "NOTE: an old system-wide unit still exists at $OLD_SYSTEM_UNIT."
        echo "      Remove it to avoid two copies of the service:"
        echo "        sudo systemctl disable --now $UNIT_NAME && sudo rm $OLD_SYSTEM_UNIT && sudo systemctl daemon-reload"
    fi
}

render_unit() {
    cat <<EOF
[Unit]
Description=openmcp webcam MCP server (stdio, user service)
After=local-fs.target

[Service]
Type=simple
WorkingDirectory=$REPO_DIR
# The server reads JSON-RPC from stdin; the tail pipe keeps stdin open so the
# process stays alive for systemd to supervise. MCP clients still spawn their
# own instance over stdio.
ExecStart=/bin/sh -c 'exec tail -f /dev/null | $PYBIN $SERVER'
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
}

case "${1:-}" in
    install)
        require_venv
        require_user_manager
        mkdir -p "$UNIT_DIR"
        render_unit > "$UNIT_FILE"
        chmod 0644 "$UNIT_FILE"
        systemctl --user daemon-reload
        systemctl --user enable "$UNIT_NAME"
        # Linger lets the service run at boot without an active login session.
        # Best effort: on some systems enabling it needs admin auth via polkit.
        if loginctl enable-linger "$USER" 2>/dev/null; then
            LINGER_NOTE="Linger enabled (service runs at boot without login)."
        else
            LINGER_NOTE="Could not enable linger (needs admin auth): the service only runs while you are logged in. Try: loginctl enable-linger $USER"
        fi
        check_old_system_unit
        echo "Installed and enabled (user service). Start now: ./rund.sh start"
        echo "$LINGER_NOTE"
        ;;
    start)
        require_installed
        require_user_manager
        systemctl --user start "$UNIT_NAME"
        systemctl --user status -n 5 --no-pager "$UNIT_NAME"
        ;;
    stop)
        require_installed
        require_user_manager
        systemctl --user stop "$UNIT_NAME"
        echo "Stopped."
        ;;
    status)
        require_installed
        require_user_manager
        systemctl --user status --no-pager "$UNIT_NAME" || true
        ;;
    unit)
        render_unit
        ;;
    *)
        echo "Usage: $0 {install|start|stop|status|unit}" >&2
        exit 2
        ;;
esac