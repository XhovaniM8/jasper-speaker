# jasper-speaker

**Voice-controlled, audiophile-grade active speaker system** running on Raspberry Pi 5.  
Built for [Jasper Tech](https://youtube.com/@JasperTech) · Engineered by Xhovani Mali

---

## Overview

A DIY active speaker system combining:

- **CamillaDSP** — multi-channel DSP/crossover/EQ pipeline
- **Music Assistant** — unified Spotify Connect, AirPlay 2, and local library
- **Home Assistant** — voice control via OpenAI + audio ducking
- **HiFiBerry DAC8x** — 8-channel balanced audio output

Everything passes through the DSP chain before hitting the speakers.

---

## Hardware

| Component              | Qty | Notes                      |
| ---------------------- | --- | -------------------------- |
| Raspberry Pi 5 (8GB)   | 3   | Main compute               |
| HiFiBerry DAC8x        | 3   | 8-ch PCM5242, balanced out |
| TPA3255 4-ch Amp Board | 3   | Powers full-range drivers  |
| HA Voice PE            | 3   | Mic input + wake word      |

---

## Quick Start

```bash
# 1. Flash Pi OS Lite (64-bit), enable SSH, set hostname to 'jasper'
# 2. Clone this repo
git clone https://github.com/xhovani/jasper-speaker.git
cd jasper-speaker

# 3. Run bootstrap
chmod +x scripts/setup.sh
./scripts/setup.sh

# 4. Verify audio chain
./scripts/test_audio.sh
```

See `docs/architecture.md` for full signal flow.

---

## Signal Flow

```
[Spotify / AirPlay / Local Library]
          ↓
    Music Assistant
          ↓
     Squeezelite
          ↓
   ALSA Loopback Device
          ↓
     CamillaDSP  ← voice/notifications also enter here
   (crossover + EQ)
          ↓
    HiFiBerry DAC8x
          ↓
   TPA3255 Amp (4-ch)
          ↓
       Speakers
```

---

## Repo Structure

```
jasper-speaker/
├── README.md
├── MILESTONES.md
├── docs/
│   ├── architecture.md       # Signal flow + design decisions
│   └── speaker-notes.md      # CamillaDSP EQ findings, FR notes
├── audio/
│   ├── camilla_config.yml    # CamillaDSP pipeline config
│   └── alsa_loopback.conf    # ALSA loopback setup
├── docker/
│   ├── docker-compose.yml    # Music Assistant + Home Assistant
│   └── .env.example          # API keys template
├── systemd/
│   └── *.service             # Boot ordering unit files
└── scripts/
    ├── setup.sh              # One-shot bootstrap
    └── test_audio.sh         # Loopback verification
```

---

## Milestones

See [MILESTONES.md](MILESTONES.md) for current progress.

---

_Xhovani Mali · FPGA/Embedded Engineer · March–April 2026_
