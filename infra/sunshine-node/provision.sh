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
  xfce4 xfce4-terminal dbus-x11

# Docker: DLAMI usually ships docker-ce + containerd.io. If absent, install docker-ce.
if ! command -v docker >/dev/null; then
  log "Installing docker-ce"
  apt-get install -y docker-ce docker-ce-cli containerd.io || apt-get install -y docker.io
fi
systemctl enable --now docker || true

# ---------------------------------------------------------------------------
# 2. NVIDIA driver sanity check (DLAMI ships drivers preinstalled).
# ---------------------------------------------------------------------------
nvidia-smi --query-gpu=name,driver_version --format=csv

GPU_INFO=$(nvidia-xconfig --query-gpu-info)
# Output line looks like:  "PCI BusID : PCI:0:30:0"  — already in the format
# Xorg expects (decimal bus:device:function). Take it verbatim.
GPU_BUS_ID=$(echo "${GPU_INFO}" | grep -oE 'PCI:[0-9]+:[0-9]+:[0-9]+' | head -1)
if [ -z "${GPU_BUS_ID}" ] || [[ ! "${GPU_BUS_ID}" =~ ^PCI: ]]; then
  log "ERROR: failed to parse PCI BusID from nvidia-xconfig. Full output:"
  echo "${GPU_INFO}" >&2
  exit 1
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
fi

# Poll for Xorg + NVIDIA renderer for up to 30s.
xorg_ready=0
for _ in $(seq 1 15); do
  GLX_OUT=$(DISPLAY=:0 glxinfo 2>/dev/null || true)
  if echo "${GLX_OUT}" | grep -qE "(server glx vendor string: NVIDIA|OpenGL vendor string: NVIDIA|OpenGL renderer.*(NVIDIA|Tesla|GeForce|Quadro|RTX|GRID))"; then
    xorg_ready=1
    break
  fi
  sleep 2
done
if [ "${xorg_ready}" -ne 1 ]; then
  log "ERROR: Xorg did not come up with the NVIDIA renderer within 30s."
  log "Check /var/log/xorg-sunshine.log and the BusID above."
  tail -50 /var/log/xorg-sunshine.log >&2 || true
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

# The Sunshine 22.04 deb is built against newer libstdc++ than Ubuntu 22.04 ships.
# Pull GCC 13 runtime from the toolchain PPA to satisfy GLIBCXX_3.4.32.
if ! strings /lib/x86_64-linux-gnu/libstdc++.so.6 2>/dev/null | grep -q "GLIBCXX_3.4.32"; then
  log "Upgrading libstdc++6 from ubuntu-toolchain-r/test PPA"
  add-apt-repository -y ppa:ubuntu-toolchain-r/test
  apt-get update -y
  apt-get install -y --only-upgrade libstdc++6
fi

# Drop our config into the ubuntu user's home.
install -d -o ubuntu -g ubuntu /home/ubuntu/.config/sunshine
install -o ubuntu -g ubuntu -m 0644 sunshine.conf /home/ubuntu/.config/sunshine/sunshine.conf

# ---------------------------------------------------------------------------
# 4b. XFCE desktop so Sunshine has something to capture.
# ---------------------------------------------------------------------------
cat >/etc/systemd/system/xfce-session.service <<'EOF'
[Unit]
Description=XFCE desktop session for Sunshine capture
After=network-online.target
Requires=network-online.target

[Service]
User=ubuntu
Environment=DISPLAY=:0
ExecStart=/usr/bin/dbus-launch --exit-with-session /usr/bin/xfce4-session
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now xfce-session
sleep 2

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
