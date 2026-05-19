#!/usr/bin/env python3
"""
lab_ssh.py — Session helper for Claude to connect to the UiPath lab jump server.

At the start of a session, Claude runs:
    from lab_ssh import LabSSH
    lab = LabSSH.from_repo(passphrase="<from project knowledge>")
    print(lab.status())

Then use:
    lab.run("oc get pods -n uipath")
    lab.run("kubectl get nodes -o wide")
    lab.cat("/opt/uipath-docs/TOC.md")
    lab.put("/opt/uipath-lab/manifests/foo.yaml", content)
    lab.search_docs("maestro agent")
"""

import base64
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path


JUMP_HOST = "20.101.72.21"
JUMP_PORT = 22
JUMP_USER = "labadmin"

# Path to encrypted private key in repo
REPO_ROOT = Path(__file__).parent
KEY_ENC = REPO_ROOT / "claude_lab_ed25519.age"


class LabSSH:
    def __init__(self, key_path: str):
        """key_path: path to decrypted private key file (temp file, deleted after use)"""
        self._key = key_path
        self._ssh_opts = [
            "-i", key_path,
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=15",
            "-p", str(JUMP_PORT),
        ]

    @classmethod
    def from_repo(cls, passphrase: str) -> "LabSSH":
        """
        Decrypt private key from repo, write to temp file, return LabSSH instance.
        Temp file is written with 0600 permissions.
        """
        try:
            import pyrage
        except ImportError:
            raise RuntimeError("pyrage not installed: pip install pyrage")

        enc_data = KEY_ENC.read_bytes()
        priv_pem = pyrage.passphrase.decrypt(enc_data, passphrase)

        # Write to temp file
        tmp = tempfile.NamedTemporaryFile(
            mode="wb", suffix="_claude_lab_key", delete=False, prefix="/tmp/"
        )
        tmp.write(priv_pem)
        tmp.close()
        os.chmod(tmp.name, 0o600)

        instance = cls(tmp.name)
        # Quick connectivity test
        try:
            result = instance._exec("date")
            print(f"[lab_ssh] Connected to jump server. Jump time: {result.strip()}")
        except Exception as e:
            os.unlink(tmp.name)
            raise RuntimeError(f"SSH connection failed: {e}")

        return instance

    def _exec(self, dispatch_cmd: str, timeout: int = 60) -> str:
        """Send a dispatch command and return stdout."""
        cmd = [
            "ssh",
            *self._ssh_opts,
            f"{JUMP_USER}@{JUMP_HOST}",
            dispatch_cmd,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0 and result.stderr:
            raise RuntimeError(f"SSH error: {result.stderr.strip()}")
        return result.stdout

    def run(self, cmd: str, timeout: int = 120) -> str:
        """Run a whitelisted command on the jump server."""
        return self._exec(f"run {cmd}", timeout=timeout)

    def cat(self, filepath: str) -> str:
        """Read a file from the jump server."""
        return self._exec(f"cat {filepath}")

    def put(self, filepath: str, content: str) -> str:
        """Write content to a file on the jump server."""
        b64 = base64.b64encode(content.encode()).decode()
        return self._exec(f"put {filepath} {b64}")

    def status(self) -> str:
        """Return cluster status summary."""
        return self._exec("status", timeout=30)

    def search_docs(self, query: str, section: str = "", top: int = 5) -> str:
        """Search UiPath docs on jump server."""
        args = f"/opt/uipath-docs/search.py {query}"
        if section:
            args += f" --section {section}"
        args += f" --top {top}"
        return self.run(f"/opt/uipath-docs/venv/bin/python3 {args}")

    def doc(self, filepath: str) -> str:
        """Read a specific doc file (relative to /opt/uipath-docs/)."""
        return self.cat(f"/opt/uipath-docs/{filepath}")

    def cleanup(self):
        """Remove temp key file."""
        try:
            os.unlink(self._key)
        except Exception:
            pass

    def __del__(self):
        self.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cleanup()


# ── Convenience: print usage if run directly ────────────────────────────────
if __name__ == "__main__":
    import sys
    print(textwrap.dedent("""
    lab_ssh.py — Claude lab SSH helper

    Usage in a Claude session:
        import sys; sys.path.insert(0, '/path/to/uipath-docs-scraper')
        from lab_ssh import LabSSH
        lab = LabSSH.from_repo(passphrase='november-lima-hotel-oscar-XXXX')

    Then:
        lab.status()
        lab.run('oc get pods -n uipath')
        lab.run('oc get nodes -o wide')
        lab.cat('/opt/uipath-docs/TOC.md')
        lab.search_docs('maestro agent orchestration')
        lab.put('/opt/uipath-lab/manifests/test.yaml', yaml_content)
    """))
