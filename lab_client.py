#!/usr/bin/env python3
"""
lab_client.py — Claude-side HTTP client for lab API.

Bruger curl (tilgængeligt i Claude's bash_tool sandbox).
API'et kører på jump:7337, eksponeret via SSH-tunnel på localhost:7337.

VIGTIGT: Kræver en aktiv SSH-tunnel:
    ssh -L 7337:localhost:7337 -N labadmin@20.101.72.21 &

Brug i Claude session:
    from lab_client import Lab
    lab = Lab(token="<fra /home/labadmin/source/uipath-docs/.lab_api_token>")
    print(lab.run("oc get nodes -o wide"))
    print(lab.run("oc get pods -n uipath | head -20"))
"""

import json
import subprocess
import sys


API_URL = "http://localhost:7337"


class Lab:
    def __init__(self, token: str):
        self.token = token
        self._headers = [
            "-H", f"Authorization: Bearer {token}",
            "-H", "Content-Type: application/json",
        ]

    def _curl(self, method: str, path: str, body: dict = None, timeout: int = 120) -> dict:
        cmd = ["curl", "-s", "--max-time", str(timeout)]
        cmd += self._headers
        if method == "POST":
            cmd += ["-X", "POST", "-d", json.dumps(body)]
        cmd.append(f"{API_URL}{path}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        if result.returncode != 0:
            raise RuntimeError(f"curl failed: {result.stderr}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"Invalid JSON response: {result.stdout[:200]}")

    def ping(self) -> bool:
        try:
            r = self._curl("GET", "/ping", timeout=5)
            return r.get("ok") is True
        except Exception:
            return False

    def run(self, cmd: str, timeout: int = 120) -> str:
        """Run a whitelisted command, return stdout."""
        r = self._curl("POST", "/run", {"cmd": cmd}, timeout=timeout)
        if "error" in r:
            raise RuntimeError(f"API error: {r['error']}")
        out = r.get("stdout", "")
        err = r.get("stderr", "")
        if err:
            out += f"\n[stderr]: {err}"
        return out

    def cat(self, filepath: str) -> str:
        """Read a file."""
        return self.run(f"cat {filepath}")

    def put(self, filepath: str, content: str) -> dict:
        """Write content to a file."""
        return self._curl("POST", "/put", {"path": filepath, "content": content})

    def status(self) -> str:
        """Cluster status summary."""
        r = self._curl("POST", "/status", {}, timeout=30)
        return "\n\n".join(f"$ {k}\n{v}" for k, v in r.items())

    def search_docs(self, query: str, section: str = "", top: int = 5) -> str:
        args = f'"/opt/uipath-docs/search.py {query}'
        if section:
            args += f" --section {section}"
        args += f" --top {top}"
        return self.run(f"/opt/uipath-docs/venv/bin/python3 {args}")


def connect(token: str = None) -> "Lab":
    """
    Convenience: opret Lab-instans og verificer forbindelse.
    Token kan også læses fra env: LAB_API_TOKEN
    """
    import os
    if token is None:
        token = os.environ.get("LAB_API_TOKEN", "")
    if not token:
        raise ValueError("Token mangler. Angiv token= eller sæt LAB_API_TOKEN.")
    lab = Lab(token)
    if not lab.ping():
        raise RuntimeError(
            "Kan ikke nå lab API på localhost:7337.\n"
            "Sørg for at SSH-tunnelen kører:\n"
            "  ssh -L 7337:localhost:7337 -N labadmin@20.101.72.21 &\n"
            "Og at lab_api.py kører på jump:\n"
            "  systemctl status lab-api"
        )
    print("[lab] Forbundet til lab API ✓")
    return lab


if __name__ == "__main__":
    print(__doc__)
