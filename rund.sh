#!/usr/bin/env bash
# Manage the openpaw MCP server as a systemd system service
# (unit: openpaw-mcp.service). Privileged steps use sudo; you may be
# asked for your password.
# Usage: ./rund.sh {install|start|stop|status|unit}
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="$(pwd -P)"
UNIT_NAME="openpaw-mcp.service"
UNIT_FILE="/etc/systemd/system/$UNIT_NAME"
PYBIN="$REPO_DIR/.venv/bin/python"
SERVER="$REPO_DIR/mcp/openpaw_mcp_server.py"
RUN_USER="${SUDO_USER:-$(stat -c %U "$REPO_DIR")}"

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

die() { echo "ERROR: $*" >&2; exit 1; }

require_venv() {
    [ -x "$PYBIN" ] || die ".venv not found — run ./setup.sh first"
}

require_installed() {
    [ -f "$UNIT_FILE" ] || die "$UNIT_NAME is not installed — run ./rund.sh install first"
}

render_unit() {
    cat <<EOF
[Unit]
Description=openmcp webcam MCP server (stdio)
After=local-fs.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO_DIR
# The server reads JSON-RPC from stdin; the tail pipe keeps stdin open so the
# process stays alive for systemd to supervise. MCP clients still spawn their
# own instance over stdio.
ExecStart=/bin/sh -c 'exec tail -f /dev/null | $PYBIN $SERVER'
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
}

case "${1:-}" in
    install)
        require_venv
        echo "Installing $UNIT_FILE (sudo password may be required)"
        TMP_UNIT="$(mktemp)"
        trap 'rm -f "$TMP_UNIT"' EXIT
        render_unit > "$TMP_UNIT"
        $SUDO install -m 0644 "$TMP_UNIT" "$UNIT_FILE"
        $SUDO systemctl daemon-reload
        $SUDO systemctl enable "$UNIT_NAME"
        echo "Installed and enabled (starts at boot). Start now: ./rund.sh start"
        ;;
    start)
        require_installed
        echo "Starting $UNIT_NAME (sudo password may be required)"
        $SUDO systemctl start "$UNIT_NAME"
        systemctl status -n 5 --no-pager "$UNIT_NAME"
        ;;
    stop)
        require_installed
        echo "Stopping $UNIT_NAME (sudo password may be required)"
        $SUDO systemctl stop "$UNIT_NAME"
        echo "Stopped."
        ;;
    status)
        require_installed
        systemctl status --no-pager "$UNIT_NAME" || true
        ;;
    unit)
        render_unit
        ;;
    *)
        echo "Usage: $0 {install|start|stop|status|unit}" >&2
        exit 2
        ;;
esac