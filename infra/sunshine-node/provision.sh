#!/usr/bin/env bash
# Provision a fresh Deep Learning Base Ubuntu 22.04 GPU instance with
# Sunshine + the moonlight-web WebRTC bridge.
#
# Usage (run on the EC2 instance, not locally):
#   sudo bash provision.sh
#
# Idempotent — safe to re-run.
#
# Expects xorg.conf and sunshine.conf to be in the same directory (we scp them
# alongside this script during launch).

set -euo pipefail
cd "$(dirname "$0")"
log() { echo "[provision $(date +%H:%M:%S)] $*" >&2; }

# ---------------------------------------------------------------------------
# 1. Wait for cloud-init / unattended-upgrades to release apt locks.
# ---------------------------------------------------------------------------
log "Waiting for apt locks..."
for _ in $(seq 1 60); do
  if ! fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 \
    && ! fuser /var/lib/apt/lists/lock   >/dev/null 2>&1; then break; fi
  sleep 5
done

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y \
  xorg xserver-xorg-core xserver-xorg-video-dummy x11-xserver-utils \
  mesa-utils pulseaudio pulseaudio-utils \
  curl wget jq ca-certificates \
  docker.io

# ---------------------------------------------------------------------------
# 2. NVIDIA driver sanity check (DLAMI ships drivers preinstalled).
# ---------------------------------------------------------------------------
nvidia-smi --query-gpu=name,driver_version --format=csv

GPU_BUS_ID=$(nvidia-xconfig --query-gpu-info \
  | awk '/PCI BusID/ {gsub(":", " ", $4); printf "PCI:%d:%d:%d", strtonum("0x"$4), strtonum("0x"$5), strtonum("0x"$6); exit}')
# Fallback parser if the above is empty.
if [ -z "${GPU_BUS_ID}" ]; then
  GPU_BUS_ID=$(nvidia-xconfig --query-gpu-info | grep "PCI BusID" | head -1 | awk '{print $4}')
fi
log "GPU BusID: ${GPU_BUS_ID}"

# ---------------------------------------------------------------------------
# 3. Write Xorg config and start X on :0.
# ---------------------------------------------------------------------------
sed "s|__GPU_BUS_ID__|${GPU_BUS_ID}|" xorg.conf > /etc/X11/xorg.conf
chmod 0644 /etc/X11/xorg.conf

# Allow Xorg to start as non-root from a console.
sed -i 's/^allowed_users=.*/allowed_users=anybody/' /etc/X11/Xwrapper.config 2>/dev/null \
  || echo "allowed_users=anybody" >> /etc/X11/Xwrapper.config

if ! pgrep -x Xorg >/dev/null; then
  systemctl stop gdm3 lightdm 2>/dev/null || true
  nohup Xorg :0 -config /etc/X11/xorg.conf -noreset \
    > /var/log/xorg-sunshine.log 2>&1 &
  sleep 4
fi

if ! DISPLAY=:0 glxinfo 2>/dev/null | grep -q "OpenGL renderer.*NVIDIA"; then
  log "ERROR: Xorg did not come up with the NVIDIA renderer."
  log "Check /var/log/xorg-sunshine.log and the BusID above."
  exit 1
fi
log "Xorg up; NVIDIA renderer active on :0."

# ---------------------------------------------------------------------------
# 4. Install Sunshine.
# ---------------------------------------------------------------------------
SUNSHINE_DEB_URL="${SUNSHINE_DEB_URL:-https://github.com/LizardByte/Sunshine/releases/latest/download/sunshine-ubuntu-22.04-amd64.deb}"
if ! command -v sunshine >/dev/null; then
  log "Installing Sunshine from ${SUNSHINE_DEB_URL}"
  curl -fsSL -o /tmp/sunshine.deb "${SUNSHINE_DEB_URL}"
  apt-get install -y /tmp/sunshine.deb
fi

# Drop our config into the ubuntu user's home.
install -d -o ubuntu -g ubuntu /home/ubuntu/.config/sunshine
install -o ubuntu -g ubuntu -m 0644 sunshine.conf /home/ubuntu/.config/sunshine/sunshine.conf

# ---------------------------------------------------------------------------
# 5. Run Sunshine under a systemd unit (system-level, runs as ubuntu user).
# ---------------------------------------------------------------------------
cat >/etc/systemd/system/sunshine.service <<'EOF'
[Unit]
Description=Sunshine GameStream host
After=network-online.target

[Service]
User=ubuntu
Environment=DISPLAY=:0
Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native
ExecStart=/usr/bin/sunshine
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now sunshine
sleep 3
systemctl --no-pager status sunshine | head -20

# ---------------------------------------------------------------------------
# 6. moonlight-web (WebRTC bridge).
#
# NOTE: image/repo path may change. Verify at:
#   https://github.com/games-on-whales/moonlight-web
# Fall back to building from source if the published image is missing.
# ---------------------------------------------------------------------------
MOONLIGHT_WEB_IMAGE="${MOONLIGHT_WEB_IMAGE:-ghcr.io/games-on-whales/moonlight-web:latest}"
if ! docker ps --format '{{.Names}}' | grep -q '^moonlight-web$'; then
  log "Starting moonlight-web container (${MOONLIGHT_WEB_IMAGE})"
  docker pull "${MOONLIGHT_WEB_IMAGE}" || {
    log "WARN: could not pull ${MOONLIGHT_WEB_IMAGE}. Skipping WebRTC bridge."
    log "      You can still verify the pipeline with the desktop Moonlight client."
    exit 0
  }
  docker run -d --name moonlight-web --restart unless-stopped \
    --network host \
    -v /opt/moonlight-web:/data \
    "${MOONLIGHT_WEB_IMAGE}"
fi

log "Provision complete."
log "  Sunshine admin UI:   https://<public-ip>:47990"
log "  moonlight-web UI:    https://<public-ip>:8443  (verify port from container logs)"
log "  Pair Moonlight first to set the admin user/pass via the Sunshine UI."
