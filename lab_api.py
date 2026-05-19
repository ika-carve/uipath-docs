#!/usr/bin/env python3
"""
lab_api.py — Minimal HTTP API på jump server.
Lytter KUN på localhost:7337 — nås via SSH-tunnel eller direkte fra jump.

Claude kalder det med:
    curl -s -X POST http://localhost:7337/run \
         -H "Authorization: Bearer <token>" \
         -H "Content-Type: application/json" \
         -d '{"cmd": "oc get pods -n uipath"}'

Start:
    python3 lab_api.py &

Stop:
    pkill -f lab_api.py

Autostart via systemd: se lab-api.service
"""

import hashlib
import hmac
import json
import logging
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
PORT = 7337
BIND = "127.0.0.1"  # localhost only — never 0.0.0.0
TOKEN_FILE = Path(__file__).parent / ".lab_api_token"
LOG_FILE = Path("/var/log/lab-api.log")
KUBECONFIG = "/opt/uipath-lab/ocp-install-new/auth/kubeconfig"

# ── Whitelist (same as dispatch.sh) ─────────────────────────────────────────
ALLOWED_PREFIXES = [
    "kubectl ",
    "oc ",
    "helm ",
    "curl ",
    "cat /opt/uipath-docs/",
    "cat /opt/uipath-lab/",
    "ls ",
    "/opt/uipath-docs/venv/bin/python3 /opt/uipath-docs/",
    "sudo /opt/uipath-lab/installer-2.2510.2/bin/uipathctl",
    "journalctl ",
    "systemctl status",
    "df ",
    "free ",
    "uptime",
    "date",
    "bash /opt/uipath-lab/",
    "python3 /opt/uipath-lab/",
    "git -C /home/labadmin/source/uipath-docs",
]

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE) if LOG_FILE.parent.exists() else logging.StreamHandler(),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def load_token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    # Generate on first run
    import secrets
    token = secrets.token_hex(32)
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)
    log.info(f"Generated new API token: {token}")
    log.info(f"Token saved to: {TOKEN_FILE}")
    return token


def is_allowed(cmd: str) -> bool:
    cmd = cmd.strip()
    for prefix in ALLOWED_PREFIXES:
        if cmd.startswith(prefix) or cmd == prefix.strip():
            return True
    return False


TOKEN = load_token()
ENV = {**os.environ, "KUBECONFIG": KUBECONFIG}


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        log.info(f"{self.address_string()} {format % args}")

    def send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def check_auth(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        supplied = auth[7:].strip()
        # Constant-time comparison
        return hmac.compare_digest(supplied.encode(), TOKEN.encode())

    def do_POST(self):
        if not self.check_auth():
            self.send_json(401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_json(400, {"error": "invalid JSON"})
            return

        if self.path == "/run":
            cmd = data.get("cmd", "").strip()
            if not cmd:
                self.send_json(400, {"error": "missing cmd"})
                return
            if not is_allowed(cmd):
                log.warning(f"DENIED: {cmd}")
                self.send_json(403, {"error": f"command not whitelisted: {cmd}"})
                return

            log.info(f"RUN: {cmd}")
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=120, env=ENV
                )
                self.send_json(200, {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "rc": result.returncode,
                })
            except subprocess.TimeoutExpired:
                self.send_json(504, {"error": "command timed out"})
            except Exception as e:
                self.send_json(500, {"error": str(e)})

        elif self.path == "/status":
            cmds = [
                "oc get nodes -o wide",
                "uptime",
            ]
            out = {}
            for c in cmds:
                r = subprocess.run(c, shell=True, capture_output=True, text=True, timeout=30, env=ENV)
                out[c] = r.stdout
            self.send_json(200, out)

        elif self.path == "/put":
            filepath = data.get("path", "")
            content = data.get("content", "")
            allowed_write = ["/opt/uipath-docs/", "/opt/uipath-lab/manifests/", "/tmp/"]
            if not any(filepath.startswith(p) for p in allowed_write):
                self.send_json(403, {"error": f"write path not allowed: {filepath}"})
                return
            try:
                Path(filepath).write_text(content)
                self.send_json(200, {"ok": True, "path": filepath})
            except Exception as e:
                self.send_json(500, {"error": str(e)})

        else:
            self.send_json(404, {"error": "unknown endpoint"})

    def do_GET(self):
        if not self.check_auth():
            self.send_json(401, {"error": "unauthorized"})
            return
        if self.path == "/ping":
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"error": "not found"})


if __name__ == "__main__":
    log.info(f"Starting lab API on {BIND}:{PORT}")
    log.info(f"Token file: {TOKEN_FILE}")
    server = HTTPServer((BIND, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopped.")
