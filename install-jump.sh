#!/bin/bash
# install-jump.sh — Run på jump server som labadmin.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_DIR="$HOME/.ssh"
DISPATCH_DIR="/opt/lab-ssh"
PUB_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKw3ye6V3IlwL8JpcR41K1aN7xqHXN1m4E3OVifSFMmM claude-lab-access"
AUTH_LINE="command=\"$DISPATCH_DIR/dispatch.sh\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $PUB_KEY"

echo "=== Installing Claude lab access ==="

# 1. dispatch.sh
sudo mkdir -p "$DISPATCH_DIR"
sudo cp "$SCRIPT_DIR/dispatch.sh" "$DISPATCH_DIR/dispatch.sh"
sudo chmod 755 "$DISPATCH_DIR/dispatch.sh"
sudo chown root:root "$DISPATCH_DIR/dispatch.sh"
echo "dispatch.sh installed"

# 2. Log files
sudo touch /var/log/lab-ssh-dispatch.log /var/log/lab-api.log
sudo chown labadmin:labadmin /var/log/lab-ssh-dispatch.log /var/log/lab-api.log

# 3. authorized_keys
mkdir -p "$SSH_DIR" && chmod 700 "$SSH_DIR"
if [[ -f "$SSH_DIR/authorized_keys" ]]; then
    grep -v "claude-lab-access" "$SSH_DIR/authorized_keys" > /tmp/ak_tmp || true
    mv /tmp/ak_tmp "$SSH_DIR/authorized_keys"
fi
echo "$AUTH_LINE" >> "$SSH_DIR/authorized_keys"
chmod 600 "$SSH_DIR/authorized_keys"
echo "authorized_keys updated"

# 4. lab-api systemd service
sudo cp "$SCRIPT_DIR/lab-api.service" /etc/systemd/system/lab-api.service
sudo systemctl daemon-reload
sudo systemctl enable lab-api
sudo systemctl restart lab-api
sleep 2
echo "lab-api service:"
sudo systemctl status lab-api --no-pager | head -8

# 5. Print token
TOKEN_FILE="$HOME/source/uipath-docs/.lab_api_token"
if [[ -f "$TOKEN_FILE" ]]; then
    echo ""
    echo "=== API Token (gem i Claude Project Knowledge som LAB_API_TOKEN) ==="
    cat "$TOKEN_FILE"
    echo ""
else
    echo "(Token genereres ved første API-start — kør: python3 $HOME/source/uipath-docs/lab_api.py)"
fi

echo ""
echo "=== Done ==="
