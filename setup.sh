#!/bin/bash
# setup.sh — Install dependencies and configure auto-update on the jump server.
# Run once as labadmin on the jump server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/uipath-docs"
VENV="$INSTALL_DIR/venv"
CRON_USER="${SUDO_USER:-labadmin}"

echo "=== UiPath Docs Scraper Setup ==="
echo "Install dir : $INSTALL_DIR"
echo "Script dir  : $SCRIPT_DIR"

# 1. Create install dir
sudo mkdir -p "$INSTALL_DIR"
sudo chown "$CRON_USER:$CRON_USER" "$INSTALL_DIR"

# 2. Copy scripts
cp -r "$SCRIPT_DIR"/. "$INSTALL_DIR/"

# 3. Python venv + deps
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip --quiet
"$VENV/bin/pip" install playwright markdownify requests --quiet

# 4. Install Playwright browser (Chromium only)
"$VENV/bin/playwright" install chromium --with-deps

echo "Dependencies installed."

# 5. Wrapper script (used by cron)
cat > "$INSTALL_DIR/run-update.sh" <<'EOF'
#!/bin/bash
cd /opt/uipath-docs
/opt/uipath-docs/venv/bin/python3 update.py --max-age-days 30 >> /opt/uipath-docs/cron.log 2>&1
EOF
chmod +x "$INSTALL_DIR/run-update.sh"

# 6. Cron: run every Sunday at 03:00
CRON_LINE="0 3 * * 0 $INSTALL_DIR/run-update.sh"
(crontab -u "$CRON_USER" -l 2>/dev/null | grep -v "uipath-docs"; echo "$CRON_LINE") \
    | crontab -u "$CRON_USER" -
echo "Cron job installed for $CRON_USER: every Sunday 03:00"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Initial scrape (takes 30-60 min):"
echo "     cd $INSTALL_DIR && venv/bin/python3 scrape.py"
echo ""
echo "  2. Or scrape a single section first to test:"
echo "     cd $INSTALL_DIR && venv/bin/python3 scrape.py --section maestro"
echo ""
echo "  3. Search:"
echo "     cd $INSTALL_DIR && venv/bin/python3 search.py 'openshift storage class'"
echo ""
echo "  Docs will be in: $INSTALL_DIR/docs/"
echo "  TOC:             $INSTALL_DIR/TOC.md"
echo "  Search index:    $INSTALL_DIR/search_index.json"
