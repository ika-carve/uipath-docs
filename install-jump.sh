#!/bin/bash
# install-jump.sh — Run på jump server som labadmin.
# Installerer dispatch.sh og tilføjer Claude's nøgle til authorized_keys.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_DIR="$HOME/.ssh"
DISPATCH_DIR="/opt/lab-ssh"
PUB_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKw3ye6V3IlwL8JpcR41K1aN7xqHXN1m4E3OVifSFMmM claude-lab-access"
AUTH_LINE="command=\"$DISPATCH_DIR/dispatch.sh\",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $PUB_KEY"

echo "=== Installing Claude lab SSH access ==="

# 1. Install dispatch script
sudo mkdir -p "$DISPATCH_DIR"
sudo cp "$SCRIPT_DIR/dispatch.sh" "$DISPATCH_DIR/dispatch.sh"
sudo chmod 755 "$DISPATCH_DIR/dispatch.sh"
sudo chown root:root "$DISPATCH_DIR/dispatch.sh"
echo "dispatch.sh installed to $DISPATCH_DIR"

# 2. Log file
sudo touch /var/log/lab-ssh-dispatch.log
sudo chown labadmin:labadmin /var/log/lab-ssh-dispatch.log
echo "Log file: /var/log/lab-ssh-dispatch.log"

# 3. authorized_keys
mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"

# Remove old claude entry if exists
if [[ -f "$SSH_DIR/authorized_keys" ]]; then
    grep -v "claude-lab-access" "$SSH_DIR/authorized_keys" > /tmp/ak_tmp || true
    mv /tmp/ak_tmp "$SSH_DIR/authorized_keys"
fi

echo "$AUTH_LINE" >> "$SSH_DIR/authorized_keys"
chmod 600 "$SSH_DIR/authorized_keys"
echo "authorized_keys updated"

# 4. Verify
echo ""
echo "=== Verification ==="
echo "dispatch.sh:"
ls -la "$DISPATCH_DIR/dispatch.sh"
echo ""
echo "authorized_keys (claude line):"
grep "claude-lab-access" "$SSH_DIR/authorized_keys"
echo ""
echo "=== Done ==="
echo ""
echo "Test fra din lokale maskine:"
echo "  ssh -i claude_lab_ed25519 -p 22 labadmin@20.101.72.21 'status'"
