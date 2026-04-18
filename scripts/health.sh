#!/usr/bin/env bash
# health.sh — Check all jasper-speaker services and API credentials
# Run as the jasper user (not root): ./scripts/health.sh
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HA_TOKEN_FILE="$REPO_DIR/.ha_token"
MA_TOKEN_FILE="$REPO_DIR/.ma_token"
HA_URL="http://localhost:8123"
MA_URL="http://localhost:8095"
CDSP_WS="ws://localhost:1234"

# Use venv Python (has websockets); fall back to system python3
PYTHON="$REPO_DIR/webui/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="python3"

PASS="✓"
FAIL="✗"
WARN="!"
errors=0

_ok()   { echo "  $PASS $1"; }
_fail() { echo "  $FAIL $1"; errors=$((errors + 1)); }
_warn() { echo "  $WARN $1"; }

echo "╔══════════════════════════════════════════╗"
echo "║      jasper-speaker health check         ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Network ───────────────────────────────────────────────────────
echo "── Network"
IP=$(hostname -I | awk '{print $1}')
if [ -n "$IP" ]; then
    _ok "Pi IP: $IP"
else
    _fail "No IP address — not connected to a network"
fi
echo ""

# ── Systemd services ──────────────────────────────────────────────
echo "── Systemd services"

# ALSA loopback — check device exists rather than service state (oneshot)
if aplay -l 2>/dev/null | grep -qi "loopback"; then
    _ok "alsa-loopback (device present)"
else
    _fail "alsa-loopback device missing"
    echo "       → Run: sudo modprobe snd-aloop pcm_substreams=2"
    echo "       → Then: sudo systemctl start alsa-loopback"
fi

for svc in camilladsp squeezelite jasper-webui; do
    state=$(systemctl is-active "$svc" 2>/dev/null)
    if [ "$state" = "active" ]; then
        _ok "$svc"
    else
        _fail "$svc ($state)"
        if [ "$svc" = "camilladsp" ]; then
            echo "       → Check config: ~/.config/camilladsp/config.yml"
            echo "       → Logs: journalctl -u camilladsp -n 20"
        fi
    fi
done
echo ""

# ── Docker containers ─────────────────────────────────────────────
echo "── Docker containers"
for container in homeassistant music-assistant faster-whisper piper; do
    state=$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || echo "not found")
    if [ "$state" = "running" ]; then
        _ok "$container"
    else
        _fail "$container ($state)"
        echo "       → Run: docker compose -f $REPO_DIR/docker/docker-compose.yml up -d $container"
    fi
done
echo ""

# ── CamillaDSP WebSocket ──────────────────────────────────────────
echo "── CamillaDSP"
CDSP_RESP=$("$PYTHON" -c "
import asyncio, websockets, json, sys
async def t():
    try:
        async with websockets.connect('$CDSP_WS', open_timeout=3) as ws:
            await ws.send(json.dumps({'GetState': None}))
            r = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
            print(r['GetState']['value'])
    except Exception as e:
        print('ERROR:' + str(e))
asyncio.run(t())
" 2>/dev/null || echo "ERROR:python3 unavailable")

if echo "$CDSP_RESP" | grep -q "^ERROR"; then
    _fail "CamillaDSP WS unreachable — ${CDSP_RESP#ERROR:}"
else
    _ok "CamillaDSP state: $CDSP_RESP"
fi
echo ""

# ── Home Assistant API ────────────────────────────────────────────
echo "── Home Assistant"
if [ ! -f "$HA_TOKEN_FILE" ]; then
    _fail ".ha_token missing"
    echo "       → Generate in HA: Profile → Security → Long-Lived Access Tokens"
    echo "       → Save to: $HA_TOKEN_FILE"
else
    HA_TOKEN=$(cat "$HA_TOKEN_FILE" | tr -d '[:space:]')
    HA_RESP=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $HA_TOKEN" "$HA_URL/api/" 2>/dev/null)
    if [ "$HA_RESP" = "200" ]; then
        _ok "HA API reachable and token valid"
    elif [ "$HA_RESP" = "401" ]; then
        _fail "HA token is invalid or expired"
        echo "       → Generate a new token in HA: Profile → Security → Long-Lived Access Tokens"
        echo "       → Replace contents of: $HA_TOKEN_FILE"
    elif [ "$HA_RESP" = "000" ]; then
        _fail "HA not reachable at $HA_URL (container down?)"
    else
        _fail "HA API returned HTTP $HA_RESP"
    fi
fi
echo ""

# ── Music Assistant API ───────────────────────────────────────────
echo "── Music Assistant"
MA_RESP=$(curl -s -o /dev/null -w "%{http_code}" "$MA_URL/" 2>/dev/null)
if [ "$MA_RESP" = "000" ]; then
    _fail "MA not reachable at $MA_URL (container down?)"
else
    _ok "MA web UI reachable ($MA_URL)"
fi

if [ ! -f "$MA_TOKEN_FILE" ]; then
    _warn ".ma_token missing — webui music control will not work"
    echo "       → Run: scripts/ma_token.sh  (creates a long-lived MA token)"
else
    MA_TOKEN=$(cat "$MA_TOKEN_FILE" | tr -d '[:space:]')
    MA_AUTH=$("$PYTHON" -c "
import asyncio, websockets, json, sys
async def t():
    try:
        async with websockets.connect('ws://localhost:8095/ws', open_timeout=3) as ws:
            await ws.recv()
            await ws.send(json.dumps({'message_id':1,'command':'auth','args':{'token':'$MA_TOKEN'}}))
            r = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            print('ok' if r.get('result',{}).get('authenticated') else 'invalid')
    except Exception as e:
        print('error:' + str(e))
asyncio.run(t())
" 2>/dev/null || echo "error:python3")
    if [ "$MA_AUTH" = "ok" ]; then
        _ok "MA token valid"
    elif echo "$MA_AUTH" | grep -q "^error"; then
        _fail "MA WS unreachable — ${MA_AUTH#error:}"
    else
        _fail "MA token invalid — re-run scripts/ma_token.sh"
    fi
fi
echo ""

# ── Voice pipeline check ──────────────────────────────────────────
echo "── Voice pipeline"
for port_label in "10300:Faster-Whisper" "10200:Piper"; do
    port="${port_label%%:*}"
    label="${port_label##*:}"
    if curl -s --connect-timeout 2 "http://localhost:$port/" &>/dev/null || \
       nc -z localhost "$port" 2>/dev/null; then
        _ok "$label (port $port)"
    else
        _warn "$label not responding on port $port — container may still be loading"
    fi
done
echo ""

# ── Summary ───────────────────────────────────────────────────────
if [ "$errors" -eq 0 ]; then
    echo "All checks passed. Jasper is ready."
else
    echo "$errors issue(s) found. See messages above."
    echo ""
    echo "Common fixes:"
    echo "  New WiFi / moved to a different network:"
    echo "    → Services should reconnect automatically (host networking)"
    echo "    → If HA token fails: regenerate it in HA UI and update .ha_token"
    echo "    → If MA token fails: run scripts/ma_token.sh"
    echo "  See docs/new-site-setup.md for full relocation checklist"
fi
echo ""
