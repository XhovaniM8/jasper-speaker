# jasper-speaker

**Voice-controlled, audiophile-grade active speaker system** running on Raspberry Pi 5.  
Built for [Jasper Tech](https://youtube.com/@JasperTech) · Engineered by Xhovani Mali

---

## Overview

A DIY active speaker system combining:

- **CamillaDSP** — multi-channel DSP/crossover/EQ pipeline
- **Music Assistant** — Spotify Connect, AirPlay 2, unified search + voice playback
- **Home Assistant** — voice control via Claude (Anthropic) + audio ducking
- **HiFiBerry DAC8x** — 8-channel balanced audio output
- **HA Voice PE** — wake word detection + microphone input

Voice responses play through the passive speakers via Music Assistant's announce channel. Music ducks automatically when the assistant speaks.

---

## Hardware

| Component              | Qty | Notes                           |
| ---------------------- | --- | ------------------------------- |
| Raspberry Pi 5 (8GB)   | 1   | Main compute                    |
| HiFiBerry DAC8x        | 1   | 8-ch PCM5242, balanced out      |
| TPA3255 4-ch Amp Board | 1   | Powers full-range drivers (DIFF mode) |
| HA Voice PE            | 1   | Mic input + wake word           |

---


## Quick Start

```bash
# 1. Flash Pi OS Lite (64-bit), enable SSH
git clone https://github.com/xhovani/jasper-speaker.git
cd jasper-speaker

# 2. Bootstrap (installs deps, systemd services, Docker)
sudo ./scripts/setup.sh
sudo reboot

# 3. Start Docker stack
cd docker && docker compose up -d

# 4. Check everything
cd .. && ./scripts/health.sh
```

Then follow the setup steps that `health.sh` reports as missing.

**Moving to a new network or new Pi?** See [`docs/new-site-setup.md`](docs/new-site-setup.md).

---

## Services

| Service          | Type    | Port  | Notes                              |
| ---------------- | ------- | ----- | ---------------------------------- |
| Home Assistant   | Docker  | 8123  | Voice pipeline, automations        |
| Music Assistant  | Docker  | 8095  | Spotify/AirPlay, player control    |
| Faster-Whisper   | Docker  | 10300 | Speech-to-text (Wyoming protocol)  |
| Piper            | Docker  | 10200 | Text-to-speech (Wyoming protocol)  |
| CamillaDSP       | systemd | 1234  | DSP pipeline WebSocket             |
| Squeezelite      | systemd | —     | ALSA loopback player               |
| Jasper Web UI    | systemd | 8080  | Dashboard + MA/CDSP control        |

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
│   ├── docker-compose.yml     # All Docker services
│   └── .env.example           # Environment template
├── systemd/
│   └── *.service              # Boot-ordered unit files
├── webui/
│   ├── app.py                 # FastAPI dashboard + MA/CDSP proxy
│   ├── index.html             # Dashboard frontend
│   └── requirements.txt
└── scripts/
    ├── setup.sh               # One-shot bootstrap
    ├── health.sh              # Service + credential health check
    ├── ma_token.sh            # Regenerate MA long-lived token
    └── test_audio.sh          # ALSA loopback verification
```

---

_Xhovani Mali · March–April 2026_
