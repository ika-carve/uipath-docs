# Claude Lab SSH Access

Sikker, begrænset SSH-adgang til jump server for Claude-sessioner.

## Arkitektur

```
Claude (bash_tool)
    │
    │  SSH med ed25519 nøgle
    ▼
jump server 20.101.72.21
    │  sshd: forced-command → dispatch.sh
    ▼
/opt/lab-ssh/dispatch.sh
    │  whitelist-tjek
    ▼
kubectl / oc / helm / uipathctl / ...
```

Nøglen i `authorized_keys` har `command=` restriction — selv hvis nøglen
lækkes kan den kun køre dispatch.sh, ikke frit shell.

## Filer

| Fil | Formål | Git |
|---|---|---|
| `claude_lab_ed25519.age` | Krypteret privat nøgle | ✓ |
| `claude_lab_ed25519.pub` | Public key | ✓ |
| `dispatch.sh` | Server-side whitelist | ✓ |
| `lab_ssh.py` | Claude session helper | ✓ |
| `install-jump.sh` | Installér på jump | ✓ |

**Aldrig commit `claude_lab_ed25519` (ukrypteret).**

## Setup (én gang)

### 1. Kopier til jump og installér

```bash
# Fra WSL/lokal maskine
cd ~/source/uipath-docs
scp install-jump.sh dispatch.sh labadmin@20.101.72.21:/tmp/
ssh labadmin@20.101.72.21 'bash /tmp/install-jump.sh'
```

### 2. Tilføj passphrase til Claude Project Knowledge

Gå til dit Claude Project → Project Knowledge → tilføj en tekst-fil med:
```
LAB_SSH_PASSPHRASE=november-lima-hotel-oscar-6309
```

## Brug i en Claude-session

Claude importerer `lab_ssh.py` fra repo'et og forbinder:

```python
import sys
sys.path.insert(0, '/path/to/uipath-docs')
from lab_ssh import LabSSH

lab = LabSSH.from_repo(passphrase='november-lima-hotel-oscar-6309')

# Cluster status
print(lab.status())

# Kør kommandoer
print(lab.run('oc get pods -n uipath'))
print(lab.run('oc get nodes -o wide'))

# Docs
print(lab.search_docs('openshift storage class'))
print(lab.doc('TOC.md'))

# Skriv en fil
lab.put('/opt/uipath-lab/manifests/test.yaml', yaml_content)
```

## Opdater whitelist

Redigér `ALLOWED_RUN` i `dispatch.sh` og kør `install-jump.sh` igen.

## Roter nøgle

```bash
# Generer ny nøgle
python3 -c "
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
import pyrage
key = Ed25519PrivateKey.generate()
priv = key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption())
enc = pyrage.passphrase.encrypt(priv, 'ny-passphrase')
open('claude_lab_ed25519.age','wb').write(enc)
pub = key.public_key().public_bytes(Encoding.OpenSSH, \
    __import__('cryptography.hazmat.primitives.serialization', fromlist=['PublicFormat']).PublicFormat.OpenSSH)
open('claude_lab_ed25519.pub','wb').write(pub)
print(pub.decode())
"
# Opdater authorized_keys på jump og Project Knowledge
```
