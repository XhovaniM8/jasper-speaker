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
**ETA:** ~1.5 weeks after M2 | **Status:** In Progress
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
- [ ] Play / pause Spotify via voice command
- [ ] Skip track / previous track via voice
- [ ] Volume up / down via voice
- [ ] Request specific song or artist via voice (stretch)

#### General Q&A via voice
- [x] Ask open-ended questions and get spoken answers (like a search engine)
- [x] Conversation agent handles knowledge questions well (not just smart-home commands)

#### TTS voice quality
- [ ] Evaluate Piper voice options and select best available voice

#### Audio ducking
- [ ] Music lowers when assistant speaks, resumes after
- [ ] CamillaDSP HA integration installed

### Deliverable
- Video demo: voice command → Spotify control + Q&A response → music resumes
### Demo
<!-- Loom link here -->
### Notes
- Claude (Haiku) is confirmed as the conversation agent — Q&A working well end to end via voice
- Music + voice integration is the current blocker — Spotify voice control in progress
- Sticking with Claude for the conversation backend; no plans to swap in Gemini or other agents
- Primary use cases: Spotify playback control + general knowledge Q&A via voice
- Current approach: Piper TTS via Wyoming — evaluate voice options before M3 is closed out
- The Pi also runs Home Assistant for Zigbee home control (lights, blinds, fans); consolidating onto the speaker hardware is possible but out of scope
---

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
