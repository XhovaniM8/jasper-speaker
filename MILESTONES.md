# Milestones

Progress tracker for the Jasper Speaker project (March–April 2026).

---

## M1 — Audio Pipeline Live

**ETA:** ~1 week from kickoff | **Status:** 🔲 In Progress

### Scope

- [ ] Pi 5 boots, DAC8x recognized by ALSA (`aplay -l` shows HiFiBerry card)
- [ ] HiFiBerry overlay added to `/boot/firmware/config.txt`
- [ ] ALSA loopback device configured
- [ ] CamillaDSP installed and running natively
- [ ] Basic 4-channel crossover config in CamillaDSP
- [ ] Squeezelite → ALSA loopback → CamillaDSP → DAC8x chain passes audio
- [ ] Music plays through test speaker
- [ ] Verified with `aplay` + `arecord` loopback test

### Deliverable

- Screen recording: `aplay -l` output + music playing through test speaker
- CamillaDSP config committed to repo (`audio/camilla_config.yml`)

### Demo

<!-- Loom link here -->

---

## M2 — Music Streaming Sources Working

**ETA:** ~1 week after M1 | **Status:** 🔲 Not Started

### Scope

- [ ] Music Assistant running in Docker
- [ ] Spotify Connect source configured and working
- [ ] AirPlay 2 source configured and working
- [ ] Local library source configured
- [ ] All sources feed into Squeezelite → DSP chain
- [ ] Volume control works across sources

### Deliverable

- Demo video: Spotify and AirPlay handoff between sources
- `docker/docker-compose.yml` committed to repo

### Demo

<!-- Loom link here -->

---

## M3 — Voice Control + Ducking

**ETA:** ~1.5 weeks after M2 | **Status:** 🔲 Not Started

### Scope

- [ ] Home Assistant running in Docker
- [ ] Voice PE mic input configured in HA voice pipeline
- [ ] OpenAI conversation agent connected
- [ ] "Jarvis" wake word triggers response
- [ ] Audio ducking: music lowers when assistant speaks, resumes after
- [ ] CamillaDSP HA integration installed
- [ ] Voice-controlled volume and EQ profile switching

### Deliverable

- Video demo: full voice command → response → music resumes flow

### Demo

<!-- Loom link here -->

---

## M4 — System Reliability & Appliance Mode

**ETA:** ~0.5 week after M3 | **Status:** 🔲 Not Started

### Scope

- [ ] Systemd service ordering: ALSA loopback → CamillaDSP → Squeezelite → Docker
- [ ] Watchdog / auto-restart on crash for all services
- [ ] Clean plug-in-and-play boot behavior
- [ ] README finalized with full setup reproduction steps
- [ ] All configs merged to `main`

### Deliverable

- Boot-to-music timing demo (video)
- Final repo with full docs merged to `main`

### Demo

<!-- Loom link here -->

---

## Release Tags

| Tag                      | Description                |
| ------------------------ | -------------------------- |
| `v0.1-m1-audio-pipeline` | M1 complete                |
| `v0.2-m2-streaming`      | M2 complete                |
| `v0.3-m3-voice`          | M3 complete                |
| `v1.0-m4-appliance`      | M4 complete — project done |
