#!/usr/bin/env bash
# ma_token.sh — Create or refresh the Music Assistant long-lived token
# Usage: ./scripts/ma_token.sh
# You will be prompted for your MA username and password.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOKEN_FILE="$REPO_DIR/.ma_token"
VENV_PYTHON="$REPO_DIR/webui/.venv/bin/python3"

PYTHON="${VENV_PYTHON:-python3}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

read -rp "MA username [jaspertech]: " MA_USER
MA_USER="${MA_USER:-jaspertech}"
read -rsp "MA password: " MA_PASS
echo ""

TOKEN=$("$PYTHON" -c "
import asyncio, websockets, json, sys

async def main():
    async with websockets.connect('ws://localhost:8095/ws') as ws:
        await ws.recv()
        await ws.send(json.dumps({'message_id':1,'command':'auth/login','args':{
            'username':'$MA_USER','password':'$MA_PASS',
            'provider_id':'builtin','device_name':'jasper-script'
        }}))
        r = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if not r.get('result',{}).get('success'):
            print('ERROR:' + r.get('result',{}).get('error','unknown'), file=sys.stderr)
            sys.exit(1)
        short_token = r['result']['access_token']

        await ws.send(json.dumps({'message_id':2,'command':'auth','args':{'token':short_token}}))
        json.loads(await asyncio.wait_for(ws.recv(), timeout=5))

        await ws.send(json.dumps({'message_id':3,'command':'auth/token/create','args':{'name':'jasper-automation'}}))
        r2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print(r2['result'])

asyncio.run(main())
" 2>&1)

if echo "$TOKEN" | grep -q "^ERROR"; then
    echo "Login failed: ${TOKEN#ERROR:}"
    echo "Check your username/password and that Music Assistant is running."
    exit 1
fi

echo "$TOKEN" > "$TOKEN_FILE"
echo "Token saved to $TOKEN_FILE"
echo "Run ./scripts/health.sh to verify."
