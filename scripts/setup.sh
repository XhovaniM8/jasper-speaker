#!/usr/bin/env bash
# setup.sh — Bootstrap jasper-speaker on a Raspberry Pi 5
# Run as root: sudo ./scripts/setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo pi)}"
USER_HOME="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"

echo "╔══════════════════════════════════════════╗"
echo "║      jasper-speaker bootstrap            ║"
echo "╚══════════════════════════════════════════╝"
echo "  Repo  : $REPO_DIR"
echo "  User  : $INSTALL_USER ($USER_HOME)"
echo ""

# ── 1. System packages ────────────────────────────────────────────
echo "[1/7] System packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    squeezelite alsa-utils curl git ca-certificates python3 python3-venv

# ── 2. ALSA loopback ──────────────────────────────────────────────
echo "[2/7] ALSA loopback module..."
echo "snd-aloop"                            > /etc/modules-load.d/snd-aloop.conf
echo "options snd-aloop pcm_substreams=2"   > /etc/modprobe.d/snd-aloop.conf
modprobe snd-aloop pcm_substreams=2 2>/dev/null || true

# ── 3. CamillaDSP binary ──────────────────────────────────────────
echo "[3/7] CamillaDSP..."
CDSP_VERSION="2.0.3"
CDSP_ARCH="aarch64-unknown-linux-gnu"
if ! /usr/local/bin/camilladsp --version 2>/dev/null | grep -q "$CDSP_VERSION"; then
    curl -fsSL "https://github.com/HEnquist/camilladsp/releases/download/v${CDSP_VERSION}/camilladsp-linux-${CDSP_ARCH}.tar.gz" \
        | tar -xz -C /usr/local/bin/ camilladsp
    chmod +x /usr/local/bin/camilladsp
    echo "    Installed CamillaDSP $CDSP_VERSION"
else
    echo "    CamillaDSP $CDSP_VERSION already installed"
fi

# ── 4. CamillaDSP config ──────────────────────────────────────────
echo "[4/7] CamillaDSP config..."
CDSP_CONF_DIR="$USER_HOME/.config/camilladsp"
mkdir -p "$CDSP_CONF_DIR"
cp "$REPO_DIR/audio/camilla_config.yml" "$CDSP_CONF_DIR/config.yml"
chown -R "$INSTALL_USER:$INSTALL_USER" "$CDSP_CONF_DIR"

# ── 5. Docker ─────────────────────────────────────────────────────
echo "[5/7] Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker "$INSTALL_USER"
    echo "    Docker installed. '$INSTALL_USER' added to docker group."
    echo "    NOTE: log out and back in (or reboot) for docker group to take effect."
else
    echo "    Docker already installed"
fi

# Docker data dirs
for dir in music-assistant whisper piper; do
    mkdir -p "$USER_HOME/$dir"
    chown "$INSTALL_USER:$INSTALL_USER" "$USER_HOME/$dir"
done

# Copy docker-compose if not present
DOCKER_DIR="$USER_HOME/jasper-speaker/docker"
mkdir -p "$DOCKER_DIR"
cp "$REPO_DIR/docker/docker-compose.yml" "$DOCKER_DIR/"
if [ ! -f "$DOCKER_DIR/.env" ]; then
    cp "$REPO_DIR/docker/.env.example" "$DOCKER_DIR/.env"
    echo "    Created docker/.env from template"
fi
chown -R "$INSTALL_USER:$INSTALL_USER" "$DOCKER_DIR"

# ── 6. Web UI venv ────────────────────────────────────────────────
echo "[6/7] Web UI Python environment..."
WEBUI_DIR="$REPO_DIR/webui"
if [ ! -d "$WEBUI_DIR/.venv" ]; then
    sudo -u "$INSTALL_USER" python3 -m venv "$WEBUI_DIR/.venv"
fi
sudo -u "$INSTALL_USER" "$WEBUI_DIR/.venv/bin/pip" install -q -r "$WEBUI_DIR/requirements.txt"
echo "    Web UI dependencies installed"

# ── 7. Systemd services ───────────────────────────────────────────
echo "[7/7] Systemd services..."

# Patch user in service files to match INSTALL_USER
for svc_src in "$REPO_DIR/systemd/"*.service; do
    svc_name="$(basename "$svc_src")"
    # Replace /home/pi and User=pi with actual user
    sed "s|/home/pi|$USER_HOME|g; s|User=pi|User=$INSTALL_USER|g; s|Group=pi|Group=$INSTALL_USER|g" \
        "$svc_src" > "/etc/systemd/system/$svc_name"
done

for svc in alsa-loopback camilladsp squeezelite jasper-docker jasper-webui; do
    systemctl enable "${svc}.service" 2>/dev/null || true
done
systemctl daemon-reload
echo "    Services enabled"

# ── HiFiBerry DAC8x overlay ───────────────────────────────────────
CONFIG_TXT="/boot/firmware/config.txt"
if [ -f "$CONFIG_TXT" ]; then
    if ! grep -q "hifiberry-dac8x" "$CONFIG_TXT"; then
        echo ""                            >> "$CONFIG_TXT"
        echo "# HiFiBerry DAC8x"          >> "$CONFIG_TXT"
        echo "dtoverlay=hifiberry-dac8x"  >> "$CONFIG_TXT"
        echo "    HiFiBerry overlay added to $CONFIG_TXT"
    else
        echo "    HiFiBerry overlay already present"
    fi
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Bootstrap complete                      ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Reboot:                    sudo reboot"
echo "  2. Start Docker stack:        cd docker && docker compose up -d"
echo "  3. Check everything:          ./scripts/health.sh"
echo "  4. Open Home Assistant:       http://$(hostname -I | awk '{print $1}'):8123"
echo "  5. Open Music Assistant:      http://$(hostname -I | awk '{print $1}'):8095"
echo ""
echo "  See docs/new-site-setup.md for full configuration walkthrough."
