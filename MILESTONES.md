# Milestones
Progress tracker for the Jasper Speaker project (March–April 2026).
---
## M1 — Audio Pipeline Live
**ETA:** ~1 week from kickoff | **Status:** Complete
### Scope
- [x] Pi 5 boots, DAC8x recognized by ALSA (`aplay -l` shows HiFiBerry card)
- [x] HiFiBerry overlay added to `/boot/firmware/config.txt`
- [x] ALSA loopback device configured
- [x] CamillaDSP installed and running natively
- [x] Stereo to 8-channel upmix config in CamillaDSP
- [x] Squeezelite → ALSA loopback → CamillaDSP → DAC8x chain passes audio
- [x] Music plays through test speaker (Dayton Audio DS90-8)
- [x] Verified with `speaker-test` and live audio playback
### Deliverable
- CamillaDSP config committed to repo (`audio/camilla_config.yml`)
### Notes
- DAC8x requires 8-channel output — stereo upmix mixer added to CamillaDSP pipeline
- DIFF mode jumpers on TPA3255 required for full balanced signal level
- Card numbering changes on reboot — loopback loaded via `/etc/modules`
---
## M2 — Music Streaming Sources Working
**ETA:** ~1 week after M1 | **Status:** Complete
### Scope
- [x] Music Assistant running in Docker
- [x] Spotify Connect source configured and working
- [x] AirPlay 2 source configured and working
- [x] All sources feed into Squeezelite → DSP chain
- [x] Volume control works across sources
### Deliverable
- `docker/docker-compose.yml` committed to repo
### Notes
- Squeezelite runs at 44100Hz 2ch into loopback, CamillaDSP handles upmix to 8ch
- systemd services created for camilladsp and squeezelite with auto-restart
---
## M3 — Voice Control + Ducking
**ETA:** ~1.5 weeks after M2 | **Status:** Complete
### Scope
#### Core pipeline (done)
- [x] Home Assistant running in Docker
- [x] Claude (Anthropic Haiku) conversation agent connected
- [x] Faster Whisper (STT) running via Wyoming protocol in Docker
- [x] Piper (TTS) running via Wyoming protocol in Docker
- [x] JasperVoice pipeline configured in HA Assist
- [x] Text commands working end to end through Claude

#### Voice hardware
- [x] Voice PE mic plugged into Pi and auto-discovered in HA
- [x] Wake word active — responds to "hello Nabu"
- [x] Custom wake word configured (e.g. "Hey Jasper")

#### Conversation agent
- [x] Switch pipeline from default Nabu Casa agent to Claude (Haiku)
- [x] Verify Q&A quality through voice end to end

#### Spotify voice control
- [x] Play / pause Spotify via voice command
- [x] Skip track / previous track via voice
- [x] Volume up / down via voice
- [x] Request specific song or artist via voice (stretch)

#### General Q&A via voice
- [x] Ask open-ended questions and get spoken answers (like a search engine)
- [x] Conversation agent handles knowledge questions well (not just smart-home commands)

#### TTS routing + Voice PE mic-only mode
- [x] TTS plays through passive speakers at full volume (not Voice PE built-in speaker)
- [x] Voice PE muted during TTS response, restored to idle
- [x] MA announce handles music pause/resume automatically — no separate gain manipulation needed

### Deliverable
- Video demo: voice command → Spotify control + Q&A response → music resumes
### Demo
<!-- Loom link here -->
### Notes
- Claude (Haiku via Anthropic HA integration) is the conversation agent
- Music Assistant HA integration connected — `media_player.jasper` exposed to Claude with full search/play/pause/skip/volume
- TTS routing: ESPHome Voice PE streams TTS via wyoming binary protocol (not media_player entity); webui TTS bridge polls HA pipeline debug WebSocket API for TTS URL, then calls `media_player.play_media` with `announce=true` on Jasper so MA handles pause/resume
- CamillaDSP ducking automations removed — they were ducking TTS (which also routes through CamillaDSP); MA announce is the correct isolation layer
---

## M3.5 — Room EQ
**ETA:** ~1 week after M3 | **Status:** Not started
### Scope
- [ ] Measure room response with HouseCurve or REW
- [ ] Generate correction filter
- [ ] Load filter into CamillaDSP pipeline
- [ ] Commit filter file to `audio/`
- [ ] Write `docs/room-eq.md` with end-to-end walkthrough
### Deliverable
- Correction filter committed to repo
- `docs/room-eq.md` with end-to-end walkthrough
### Notes
- HouseCurve ($20/yr, phone mic) is the simpler path; REW (free, requires measurement mic) is more precise
- Single test speaker on a table is not ideal for room correction — goal at this stage is to learn the measurement → filter → DSP workflow
- CamillaDSP supports loading REW filters directly: https://github.com/HEnquist/camilladsp#using-filters-from-rew
- Measurement mics are available
### Resources
- HouseCurve auto-EQ docs: https://housecurve.com/docs/tuning/equalization#automatic-equalization
- REW: https://www.roomeqwizard.com/
---
## M4 — Appliance Polish
**ETA:** ~1 week after M3.5 | **Status:** In progress
### Scope
- [x] All services auto-restart cleanly after power loss
- [x] Boot service ordering hardened (alsa-loopback → camilladsp → squeezelite → webui; jasper-docker for containers)
- [x] All Docker services consolidated into `docker/docker-compose.yml` (HA was standalone)
- [x] HA config committed to repo under `homeassistant/`
- [ ] Boot-to-music time under 30s verified
- [ ] Final repo docs complete and merged to `main`
- [ ] Tag `v1.0-m4-appliance`
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
| `v0.3.5-m3.5-room-eq`    | M3.5 complete              |
| `v1.0-m4-appliance`      | M4 complete — project done |
