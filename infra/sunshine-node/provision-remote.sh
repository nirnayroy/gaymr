#!/usr/bin/env bash
# Copy the Sunshine recipe to a running EC2 instance and run it.
#
# Usage:
#   ./provision-remote.sh <public-ip>
#   ./provision-remote.sh           # uses .last-public-ip from launch.sh

set -euo pipefail
cd "$(dirname "$0")"

PUBLIC_IP="${1:-$(cat .last-public-ip 2>/dev/null || true)}"
KEY="${KEY:-$HOME/.ssh/gaymr-sunshine-mumbai.pem}"
[ -n "$PUBLIC_IP" ] || { echo "Usage: $0 <public-ip>"; exit 1; }
[ -f "$KEY" ] || { echo "Private key not found: $KEY"; exit 1; }

SSH_OPTS=(-i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

echo "[remote] Waiting for ssh on ${PUBLIC_IP}..."
for _ in $(seq 1 30); do
  if ssh "${SSH_OPTS[@]}" "ubuntu@${PUBLIC_IP}" 'true' 2>/dev/null; then break; fi
  sleep 5
done

echo "[remote] Copying recipe..."
scp "${SSH_OPTS[@]}" provision.sh xorg.conf sunshine.conf "ubuntu@${PUBLIC_IP}:/tmp/"

echo "[remote] Running provision.sh (this takes ~3-5 min)..."
ssh "${SSH_OPTS[@]}" "ubuntu@${PUBLIC_IP}" \
  'cd /tmp && sudo bash provision.sh'

cat <<EOF

[remote] Provisioning finished. Verify in the browser:

  Sunshine admin UI:   https://${PUBLIC_IP}:47990
  moonlight-web UI:    https://${PUBLIC_IP}:8443

Both serve self-signed certs — accept the browser warning. Pair flow is
documented in the README.

EOF
