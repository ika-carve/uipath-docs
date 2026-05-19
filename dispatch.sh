#!/bin/bash
# /opt/lab-ssh/dispatch.sh
# Called by sshd via forced-command in authorized_keys.
# Only allows a curated set of commands — Claude cannot get free shell.
#
# Protocol: client sends command as SSH command argument ($SSH_ORIGINAL_COMMAND)
# Format:   <verb> [args...]
#
# Verbs:
#   run <cmd>          — run whitelisted command, return output
#   cat <file>         — read file under allowed paths
#   put <file> <b64>   — write base64-encoded content to allowed path
#   status             — cluster/pod summary

set -euo pipefail

LOG="/var/log/lab-ssh-dispatch.log"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

log() { echo "$TS [dispatch] $*" >> "$LOG"; }

CMD="${SSH_ORIGINAL_COMMAND:-}"
log "invoked: $CMD"

if [[ -z "$CMD" ]]; then
    echo "ERROR: no command. Use: run <cmd> | cat <file> | put <file> <b64> | status"
    exit 1
fi

verb=$(echo "$CMD" | awk '{print $1}')
rest=$(echo "$CMD" | cut -d' ' -f2-)

# ── Allowed run commands ────────────────────────────────────────────────────
ALLOWED_RUN=(
    "kubectl "
    "oc "
    "helm "
    "curl "
    "cat /opt/uipath-docs/"
    "ls "
    "/opt/uipath-docs/venv/bin/python3 /opt/uipath-docs/search.py"
    "/opt/uipath-docs/venv/bin/python3 /opt/uipath-docs/update.py"
    "/opt/uipath-docs/venv/bin/python3 /opt/uipath-docs/scrape.py"
    "sudo /opt/uipath-lab/installer-2.2510.2/bin/uipathctl"
    "journalctl "
    "systemctl status"
    "df "
    "free "
    "uptime"
    "date"
    "id"
    "bash /opt/uipath-lab/"
    "python3 /opt/uipath-lab/"
)

# ── Allowed file read paths ─────────────────────────────────────────────────
ALLOWED_READ_PREFIXES=(
    "/opt/uipath-docs/"
    "/opt/uipath-lab/"
    "/tmp/"
    "/var/log/lab-ssh-dispatch.log"
)

# ── Allowed file write paths ────────────────────────────────────────────────
ALLOWED_WRITE_PREFIXES=(
    "/opt/uipath-docs/"
    "/opt/uipath-lab/manifests/"
    "/tmp/"
)

# ── Export kubeconfig so kubectl/oc work ────────────────────────────────────
export KUBECONFIG="/opt/uipath-lab/ocp-install-new/auth/kubeconfig"

case "$verb" in

    run)
        allowed=false
        for pattern in "${ALLOWED_RUN[@]}"; do
            if [[ "$rest" == $pattern* ]]; then
                allowed=true
                break
            fi
        done
        if [[ "$allowed" != true ]]; then
            log "DENIED run: $rest"
            echo "ERROR: command not whitelisted: $rest"
            exit 1
        fi
        log "run: $rest"
        eval "$rest" 2>&1
        ;;

    cat)
        filepath="$rest"
        allowed=false
        for prefix in "${ALLOWED_READ_PREFIXES[@]}"; do
            if [[ "$filepath" == $prefix* ]]; then
                allowed=true
                break
            fi
        done
        if [[ "$allowed" != true ]]; then
            log "DENIED cat: $filepath"
            echo "ERROR: path not allowed: $filepath"
            exit 1
        fi
        if [[ ! -f "$filepath" ]]; then
            echo "ERROR: file not found: $filepath"
            exit 1
        fi
        log "cat: $filepath"
        cat "$filepath"
        ;;

    put)
        # put <filepath> <base64content>
        filepath=$(echo "$rest" | awk '{print $1}')
        b64=$(echo "$rest" | cut -d' ' -f2-)
        allowed=false
        for prefix in "${ALLOWED_WRITE_PREFIXES[@]}"; do
            if [[ "$filepath" == $prefix* ]]; then
                allowed=true
                break
            fi
        done
        if [[ "$allowed" != true ]]; then
            log "DENIED put: $filepath"
            echo "ERROR: write path not allowed: $filepath"
            exit 1
        fi
        log "put: $filepath"
        echo "$b64" | base64 -d > "$filepath"
        echo "OK: wrote $filepath"
        ;;

    status)
        log "status"
        echo "=== Cluster nodes ==="
        oc get nodes -o wide 2>&1 | head -20
        echo ""
        echo "=== UiPath namespace pods (not Running) ==="
        oc get pods -n uipath --field-selector=status.phase!=Running 2>&1 | head -30
        echo ""
        echo "=== ArgoCD apps ==="
        oc get applications -n argocd 2>&1 | head -20
        echo ""
        echo "=== Jump server load ==="
        uptime
        ;;

    *)
        log "unknown verb: $verb"
        echo "ERROR: unknown verb '$verb'. Valid: run | cat | put | status"
        exit 1
        ;;
esac
