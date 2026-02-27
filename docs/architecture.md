# Architecture

## Signal Flow

```
┌─────────────────────────────────────────────────┐
│              Audio Sources                       │
│  Spotify Connect │ AirPlay 2 │ Local Library     │
└──────────────────┬──────────────────────────────┘
                   ↓
         ┌─────────────────┐
         │ Music Assistant │  (Docker)
         │   (MA server)   │
         └────────┬────────┘
                  ↓
         ┌─────────────────┐
         │   Squeezelite   │  (native, controlled by MA)
         │  (LMS player)   │
         └────────┬────────┘
                  ↓
         ┌─────────────────┐
         │  ALSA Loopback  │  (virtual device — the mixing bus)
         │  (hw:Loopback)  │ ←── voice responses + notifications
         └────────┬────────┘       also enter here via HA
                  ↓
         ┌─────────────────┐
         │   CamillaDSP    │  (native, real-time DSP)
         │  crossover + EQ │
         │  4-ch pipeline  │
         └────────┬────────┘
                  ↓
         ┌─────────────────┐
         │  HiFiBerry DAC8x│  (hw:sndrpihifiberry)
         │ 8-ch balanced   │
         └────────┬────────┘
                  ↓
         ┌─────────────────┐
         │  TPA3255 Amp    │  4-channel class D
         └────────┬────────┘
                  ↓
              Speakers
```

## Voice / Ducking Flow

```
Voice PE mic → wake word detection
                     ↓
              Home Assistant  (Docker)
              voice pipeline
                     ↓
              OpenAI API  (cloud)
              (conversation agent)
                     ↓
              HA sends TTS audio
              to ALSA loopback
                     ↓
              CamillaDSP
              (plays response)

Ducking: HA CamillaDSP integration → volume down on speech start
                                    → volume restore on speech end
```

---

## Component Roles

**Squeezelite** acts as the LMS player client, controlled entirely by Music Assistant. Its sole job is to decode audio and write PCM to the ALSA loopback. It never touches hardware directly.

**ALSA Loopback** is the central mixing bus. Every audio source — music, TTS, notifications — writes to the loopback. CamillaDSP reads from it. This ensures a single, unified processing chain.

**CamillaDSP** is the DSP engine. It reads from the loopback in real time and applies a configurable pipeline: active crossover filters split frequencies to appropriate drivers, EQ corrects for speaker/room response, and output goes to the DAC's 8 channels.

**Music Assistant** handles all streaming providers. It abstracts Spotify Connect, AirPlay 2, and local library into a unified interface, and exposes Squeezelite as a controllable player endpoint.

**Home Assistant** is the coordinator. It holds API keys, manages the voice pipeline (mic → STT → LLM → TTS), and exposes CamillaDSP as a HA entity so automations and voice commands can adjust volume, mute, and switch EQ profiles.

---

## Design Decisions

**Why ALSA loopback as mixing bus?**  
CamillaDSP captures from a single ALSA device. The loopback lets multiple sources (Squeezelite, TTS) write to one virtual device without needing a full JACK setup or PulseAudio. Lower latency, simpler config.

**Why native CamillaDSP (not Docker)?**  
Real-time audio processing benefits from direct hardware access and minimal scheduling jitter. Running CamillaDSP natively avoids Docker networking overhead for ALSA devices.

**Why Docker for MA + HA?**  
These services have complex dependency trees and benefit from containerization. They're not latency-sensitive and the isolation keeps the OS clean.

**4-channel crossover config**  
The TPA3255 amp is 4-channel. CamillaDSP splits the signal into: low (woofer L/R) and full-range or high (tweeter L/R), depending on final driver selection. Config in `audio/camilla_config.yml`.

---

## Port / Interface Map

| Service              | Port | Notes                        |
| -------------------- | ---- | ---------------------------- |
| Music Assistant      | 8095 | Web UI                       |
| Home Assistant       | 8123 | Web UI                       |
| CamillaDSP websocket | 1234 | HA integration connects here |
| Squeezelite          | —    | Controlled via LMS protocol  |
