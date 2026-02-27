#!/usr/bin/env bash
# setup.sh — One-shot bootstrap for jasper-speaker on Raspberry Pi 5
# Run as: sudo ./scripts/setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_HOME="/home/pi"

echo "==> jasper-speaker bootstrap"
echo "    Repo: $REPO_DIR"
echo ""

# ----------------------------------------------------------------
# 1. System dependencies
# ----------------------------------------------------------------
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y --no-install-recommends \
    squeezelite \
    alsa-utils \
    curl \
    git \
    ca-certificates

# ----------------------------------------------------------------
# 2. ALSA loopback module
# ----------------------------------------------------------------
echo "[2/7] Configuring ALSA loopback..."
echo "snd-aloop" > /etc/modules-load.d/snd-aloop.conf
echo "options snd-aloop pcm_substreams=2" > /etc/modprobe.d/snd-aloop.conf
modprobe snd-aloop pcm_substreams=2 || true

# ----------------------------------------------------------------
# 3. CamillaDSP — download latest release binary
# ----------------------------------------------------------------
echo "[3/7] Installing CamillaDSP..."
CDSP_VERSION="2.0.3"
CDSP_ARCH="aarch64-unknown-linux-gnu"
CDSP_URL="https://github.com/HEnquist/camilladsp/releases/download/v${CDSP_VERSION}/camilladsp-linux-${CDSP_ARCH}.tar.gz"

curl -fsSL "$CDSP_URL" | tar -xz -C /usr/local/bin/ camilladsp
chmod +x /usr/local/bin/camilladsp
echo "    CamillaDSP $CDSP_VERSION installed at /usr/local/bin/camilladsp"

# ----------------------------------------------------------------
# 4. Copy CamillaDSP config
# ----------------------------------------------------------------
echo "[4/7] Installing CamillaDSP config..."
mkdir -p "$USER_HOME/jasper-speaker/audio"
cp "$REPO_DIR/audio/camilla_config.yml" "$USER_HOME/jasper-speaker/audio/"
chown -R pi:pi "$USER_HOME/jasper-speaker"

# ----------------------------------------------------------------
# 5. Docker
# ----------------------------------------------------------------
echo "[5/7] Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker pi
    echo "    Docker installed. 'pi' added to docker group."
else
    echo "    Docker already installed, skipping."
fi

# Copy docker compose files if not already present
DOCKER_DIR="$USER_HOME/jasper-speaker/docker"
mkdir -p "$DOCKER_DIR"
cp "$REPO_DIR/docker/docker-compose.yml" "$DOCKER_DIR/"
if [ ! -f "$DOCKER_DIR/.env" ]; then
    cp "$REPO_DIR/docker/.env.example" "$DOCKER_DIR/.env"
    echo "    Copied .env.example → docker/.env — fill in API keys before starting."
fi
chown -R pi:pi "$DOCKER_DIR"

# ----------------------------------------------------------------
# 6. Systemd services
# ----------------------------------------------------------------
echo "[6/7] Installing systemd services..."
SYSTEMD_DIR="/etc/systemd/system"
for svc in alsa-loopback camilladsp squeezelite jasper-docker; do
    cp "$REPO_DIR/systemd/${svc}.service" "$SYSTEMD_DIR/"
    systemctl enable "${svc}.service"
done
systemctl daemon-reload
echo "    Services enabled: alsa-loopback → camilladsp → squeezelite → jasper-docker"

# ----------------------------------------------------------------
# 7. HiFiBerry DAC8x overlay
# ----------------------------------------------------------------
CONFIG_TXT="/boot/firmware/config.txt"
echo "[7/7] Checking HiFiBerry DAC8x overlay in $CONFIG_TXT..."
if grep -q "hifiberry-dac8x" "$CONFIG_TXT"; then
    echo "    Overlay already present."
else
    echo "" >> "$CONFIG_TXT"
    echo "# HiFiBerry DAC8x" >> "$CONFIG_TXT"
    echo "dtoverlay=hifiberry-dac8x" >> "$CONFIG_TXT"
    echo "    Overlay added. Reboot required for DAC8x to appear."
fi

# ----------------------------------------------------------------
echo ""
echo "Bootstrap complete."
echo ""
echo "Next steps:"
echo "  1. Edit $DOCKER_DIR/.env — add OPENAI_API_KEY and other secrets"
echo "  2. Reboot: sudo reboot"
echo "  3. After reboot, verify with: ./scripts/test_audio.sh"
