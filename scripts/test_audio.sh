#!/usr/bin/env bash
# test_audio.sh — Verify the full audio chain
# Usage: ./scripts/test_audio.sh
set -euo pipefail

PASS=0
FAIL=0

ok()   { echo "  [PASS] $1"; ((PASS++)); }
fail() { echo "  [FAIL] $1"; ((FAIL++)); }
info() { echo "  [INFO] $1"; }

echo "==> jasper-speaker audio chain test"
echo ""

# ----------------------------------------------------------------
# 1. ALSA cards
# ----------------------------------------------------------------
echo "[1] ALSA cards (aplay -l)"
aplay -l 2>/dev/null || true
echo ""

echo "[2] Checking for HiFiBerry DAC8x..."
if aplay -l 2>/dev/null | grep -qi "hifiberry\|sndrpihifiberry"; then
    ok "HiFiBerry DAC8x detected"
else
    fail "HiFiBerry DAC8x NOT found — check dtoverlay in /boot/firmware/config.txt"
fi

echo ""
echo "[3] Checking for ALSA loopback..."
if aplay -l 2>/dev/null | grep -qi "loopback"; then
    ok "ALSA loopback device present"
else
    fail "ALSA loopback NOT found — run: sudo modprobe snd-aloop pcm_substreams=2"
fi

# ----------------------------------------------------------------
# 2. Services
# ----------------------------------------------------------------
echo ""
echo "[4] Checking systemd services..."
for svc in alsa-loopback camilladsp squeezelite; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        ok "$svc is running"
    else
        fail "$svc is NOT running (systemctl status $svc)"
    fi
done

# ----------------------------------------------------------------
# 3. CamillaDSP websocket
# ----------------------------------------------------------------
echo ""
echo "[5] Checking CamillaDSP websocket (port 1234)..."
if command -v nc &>/dev/null; then
    if nc -z localhost 1234 2>/dev/null; then
        ok "CamillaDSP websocket reachable on port 1234"
    else
        fail "CamillaDSP websocket not reachable on port 1234"
    fi
else
    info "nc not available — skipping websocket check"
fi

# ----------------------------------------------------------------
# 4. Loopback audio test
# ----------------------------------------------------------------
echo ""
echo "[6] Loopback write/read test (2 seconds)..."
if aplay -l 2>/dev/null | grep -qi "loopback"; then
    # Write a sine tone to loopback write side, capture from read side simultaneously
    TMP_OUT=$(mktemp /tmp/loopback_test_XXXXXX.wav)
    arecord -D hw:Loopback,1 -f S16_LE -r 48000 -c 2 -d 2 "$TMP_OUT" &
    REC_PID=$!
    speaker-test -D hw:Loopback,0 -t sine -f 1000 -l 1 -s 1 &>/dev/null &
    PLAY_PID=$!
    wait $REC_PID 2>/dev/null || true
    kill $PLAY_PID 2>/dev/null || true

    # Check recorded file has non-zero size
    if [ -s "$TMP_OUT" ]; then
        ok "Loopback record captured audio ($(du -h "$TMP_OUT" | cut -f1))"
    else
        fail "Loopback record produced empty file"
    fi
    rm -f "$TMP_OUT"
else
    info "Skipping loopback test — device not present"
fi

# ----------------------------------------------------------------
echo ""
echo "-------------------------------"
echo "  Results: $PASS passed, $FAIL failed"
echo "-------------------------------"
if [ "$FAIL" -gt 0 ]; then
    echo "  Some checks failed. Review output above."
    exit 1
else
    echo "  All checks passed."
fi
