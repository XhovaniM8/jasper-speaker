# Moving Jasper to a New Location

Use this when setting up on a new network, new Pi, or after a fresh OS flash.

---

## 1. First-time setup (new Pi)

```bash
git clone https://github.com/XhovaniM8/jasper-speaker.git
cd jasper-speaker
sudo ./scripts/setup.sh
sudo reboot
```

After reboot:

```bash
cd ~/jasper-speaker/docker
docker compose up -d
```

Then follow the steps below to configure credentials.

---

## 2. New network (same Pi, different WiFi)

Services use `host` networking and bind to `localhost`, so they reconnect automatically. No config changes needed for the audio chain.

**What does require action:**

| Thing | Why | Fix |
|---|---|---|
| `.ha_token` | HA long-lived tokens are instance-specific | Regenerate in HA (see below) |
| `.ma_token` | MA token tied to the MA instance | Run `scripts/ma_token.sh` |
| Voice PE pairing | ESPHome device finds HA by IP/mDNS | Usually auto-reconnects; re-adopt in HA if not |

Run `./scripts/health.sh` — it will call out exactly what's broken.

---

## 3. Regenerate the HA token

**Option A — via HA UI (preferred):**

1. Open Home Assistant: `http://<pi-ip>:8123`
2. Profile (bottom-left) → **Security** tab
3. Scroll to **Long-Lived Access Tokens** → **Create Token**
4. Name it `jasper-script`, copy the token
5. Save it:
   ```bash
   echo 'YOUR_TOKEN_HERE' > ~/.ha_token
   ```

**Option B — via SSH without UI access** (token expired or HA updated and revoked it):

```bash
# Find the existing long-lived token record and re-sign it
sudo python3 -c "
import json, time, base64, hmac, hashlib

with open('/home/jaspertech/homeassistant/.storage/auth') as f:
    d = json.load(f)

# Find the long_lived_access_token record
t = next(r for r in d['data']['refresh_tokens']
         if r['token_type'] == 'long_lived_access_token')

jwt_key = t['jwt_key']
token_id = t['id']
now = int(time.time())
exp = now + 10 * 365 * 24 * 3600  # 10 years

def b64url(data):
    if isinstance(data, str): data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

header  = b64url(json.dumps({'alg':'HS256','typ':'JWT'}))
payload = b64url(json.dumps({'iss': token_id, 'iat': now, 'exp': exp}))
msg = f'{header}.{payload}'
sig = hmac.new(jwt_key.encode(), msg.encode(), hashlib.sha256).digest()
jwt = f'{msg}.{b64url(sig)}'

with open('/home/jaspertech/.ha_token', 'w') as f:
    f.write(jwt)
print('Token written. Test with: curl -s -H \"Authorization: Bearer \$(cat ~/.ha_token)\" http://localhost:8123/api/')
"
```

> **Why this happens:** HA can invalidate stored tokens on major updates. The token in `.ha_token` references a refresh token record in HA's auth storage by its `iss` field. If that record was deleted, the token gets a 401. Option B re-signs a fresh JWT using the current record's key without touching HA auth state.

---

## 4. Regenerate the MA token

```bash
cd ~/jasper-speaker
./scripts/ma_token.sh
```

You'll be prompted for your MA username and password. The default username is `jaspertech`.

If you've forgotten the MA password, it can be reset by stopping Music Assistant and running:

```bash
docker stop music-assistant
docker run --rm -v ~/music-assistant:/data python:3.13-slim python3 -c "
import hashlib, sqlite3
user_id = '<your-user-id-from-auth.db>'
server_id = '<from-settings.json>'
new_pw = 'jasper123'
salt = f'{user_id}:{server_id}'
h = hashlib.pbkdf2_hmac('sha256', new_pw.encode(), salt.encode(), 100000).hex()
conn = sqlite3.connect('/data/auth.db')
conn.execute('UPDATE user_auth_providers SET provider_user_id=? WHERE provider_type=?', (h,'builtin'))
conn.commit()
conn.close()
print('Password reset to: jasper123')
"
docker start music-assistant
```

---

## 5. Anthropic API key

The Anthropic key lives inside Home Assistant, not in any file here.

1. Open HA → Settings → Integrations → **Claude**
2. If missing: Add Integration → Anthropic → enter your `sk-ant-...` key
3. The conversation agent and voice pipeline use it automatically

---

## 6. Spotify

Spotify credentials live inside Music Assistant.

1. Open MA: `http://<pi-ip>:8095`
2. Settings → Providers → **Spotify** → log in with your Spotify account

---

## 7. Voice PE (HA Voice device)

The Voice PE finds HA via mDNS (`homeassistant.local`). On a new network it should auto-discover. If not:

1. Hold the button on the Voice PE for 5s to enter pairing mode
2. In HA: Settings → Devices → Add Device → ESPHome

---

## 8. Verify everything

```bash
./scripts/health.sh
```

All green = ready. Any failures include the exact fix.

---

## Known limitations

- **Multiple speakers** — Each Pi should have a unique Squeezelite player name (set via `-n` in `squeezelite.service`). Set `JASPER_PLAYER_NAME` in the webui environment to match so the dashboard controls the right player.
- **HA + MA tokens** — These are not in the repo (`.gitignore`). They must be created fresh on any new setup.
