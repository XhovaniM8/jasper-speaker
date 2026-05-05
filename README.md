# jasper-speaker

**Voice-controlled, audiophile-grade active speaker system** running on Raspberry Pi 5.  
Built for [Jasper Tech](https://youtube.com/@JasperTech) · Engineered by Xhovani Mali

---

## Overview

A DIY active speaker system combining:

- **CamillaDSP** — multi-channel DSP/crossover/EQ pipeline
- **Music Assistant** — Spotify Connect, AirPlay 2, unified search + voice playback
- **Home Assistant** — voice control via Claude (Anthropic) + TTS routing
- **HiFiBerry DAC8x** — 8-channel balanced audio output
- **HA Voice PE** — wake word detection + microphone input (speaker silenced)

Voice responses play through the passive speakers via Music Assistant's announce channel. The Voice PE acts as a pure mic satellite — its built-in speaker is muted during TTS so all audio comes from the main drivers.

---

## How Voice Works

```
Voice PE (mic) → wake word → HA pipeline → Faster-Whisper (STT)
    → Claude (conversation) → Piper (TTS) → webui TTS bridge
    → media_player.jasper (announce) → Squeezelite → CamillaDSP → speakers
```

The key piece is the **TTS bridge** (`POST /api/tts_bridge` on the webui). When the
satellite enters `responding` state, an HA automation mutes the Voice PE speaker and
calls the bridge. The bridge polls HA's pipeline debug WebSocket API until Piper
finishes generating, then plays the TTS URL on `media_player.jasper` with
`announce=true`. Music Assistant pauses the current track, plays the TTS at full volume
through the DSP chain, then resumes automatically.

---

## Hardware

| Component              | Qty | Notes                           |
| ---------------------- | --- | ------------------------------- |
| Raspberry Pi 5 (8GB)   | 1   | Main compute                    |
| HiFiBerry DAC8x        | 1   | 8-ch PCM5242, balanced out      |
| TPA3255 4-ch Amp Board | 1   | Powers full-range drivers (DIFF mode) |
| HA Voice PE            | 1   | Mic input + wake word only      |

---

## Quick Start

```bash
# 1. Flash Pi OS Lite (64-bit), enable SSH
git clone https://github.com/XhovaniM8/jasper-speaker.git
cd jasper-speaker

# 2. Bootstrap (installs deps, systemd services, Docker)
sudo ./scripts/setup.sh
sudo reboot

# 3. Start Docker stack (HA + MA + Piper + Faster-Whisper)
cd docker && docker compose up -d

# 4. Check everything
cd .. && ./scripts/health.sh
```

Then follow the setup steps that `health.sh` reports as missing.

**Moving to a new network or new Pi?** See [`docs/new-site-setup.md`](docs/new-site-setup.md).

---

## Services

| Service          | Type    | Port  | Notes                                   |
| ---------------- | ------- | ----- | --------------------------------------- |
| Home Assistant   | Docker  | 8123  | Voice pipeline, automations             |
| Music Assistant  | Docker  | 8095  | Spotify/AirPlay, player control         |
| Faster-Whisper   | Docker  | 10300 | Speech-to-text (Wyoming protocol)       |
| Piper            | Docker  | 10200 | Text-to-speech (Wyoming protocol)       |
| CamillaDSP       | systemd | 1234  | DSP pipeline + WebSocket control        |
| Squeezelite      | systemd | —     | ALSA loopback → CamillaDSP player       |
| Jasper Web UI    | systemd | 8080  | Dashboard, MA/CDSP proxy, TTS bridge    |

### Boot order

```
alsa-loopback → camilladsp → squeezelite → jasper-webui
docker → jasper-docker (docker compose up -d)
```

All systemd units have `Restart=always`; all Docker containers have `restart: unless-stopped`.

---

## Webui API

| Endpoint                    | Method | Description                                    |
| --------------------------- | ------ | ---------------------------------------------- |
| `/api/status`               | GET    | Service health (systemd + Docker)              |
| `/api/ma/play`              | POST   | Search MA and play on Jasper                   |
| `/api/ma/pause`             | POST   | Pause                                          |
| `/api/ma/resume`            | POST   | Resume                                         |
| `/api/ma/next`              | POST   | Next track                                     |
| `/api/ma/previous`          | POST   | Previous track                                 |
| `/api/ma/volume`            | POST   | Set volume (0–100)                             |
| `/api/ma/status`            | GET    | Current track / player state                   |
| `/api/tts_bridge`           | POST   | Poll HA pipeline debug → play TTS on Jasper    |
| `/api/duck/start`           | POST   | Lower CamillaDSP gain 20 dB (manual duck)      |
| `/api/duck/end`             | POST   | Restore CamillaDSP gain                        |
| `/api/services/{svc}/{act}` | POST   | start/stop/restart a systemd or Docker service |
| `/ws/cdsp`                  | WS     | Proxy to CamillaDSP WebSocket (port 1234)      |

---

## HA Config

Reference copies of the live HA config files live in `homeassistant/`. Apply them to
`/home/jaspertech/homeassistant/` (the Docker volume mount) when setting up a fresh
instance.

Key automations:
- `tts_mirror_to_jasper` — mutes Voice PE, calls `/api/tts_bridge` when satellite responds
- `restore_voice_pe_volume` — restores Voice PE volume when satellite returns to idle

---

## Repo Structure

```
jasper-speaker/
├── README.md
├── MILESTONES.md
├── docs/
│   ├── architecture.md        # Design decisions
│   ├── new-site-setup.md      # Relocation / new network guide
│   └── speaker-notes.md       # CamillaDSP EQ notes
├── audio/
│   ├── camilla_config.yml     # CamillaDSP pipeline config
│   └── alsa_loopback.conf     # ALSA loopback setup
├── docker/
│   └── docker-compose.yml     # All Docker services (HA + MA + Piper + Whisper)
├── homeassistant/
│   ├── configuration.yaml     # HA core config + rest_commands
│   ├── automations.yaml       # TTS routing + Voice PE mute
│   └── scripts.yaml           # Jasper voice control scripts
├── systemd/
│   └── *.service              # Boot-ordered unit files
├── webui/
│   ├── app.py                 # FastAPI dashboard + MA/CDSP proxy + TTS bridge
│   ├── index.html             # Dashboard frontend
│   └── requirements.txt
└── scripts/
    ├── setup.sh               # One-shot bootstrap
    ├── health.sh              # Service + credential health check
    ├── ma_token.sh            # Regenerate MA long-lived token
    └── test_audio.sh          # ALSA loopback verification
```

---

_Xhovani Mali · March–May 2026_
