"""
jasper-speaker Web Dashboard — FastAPI backend
Serves on port 8080, proxies CamillaDSP WS, exposes system control endpoints.
"""

import asyncio
import copy
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("jasper")

import yaml
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.websockets import WebSocketState

app = FastAPI(title="Jasper Speaker Dashboard")

BASE_DIR = Path(__file__).parent
REPO_DIR = BASE_DIR.parent
CONFIG_PATH = REPO_DIR / "audio" / "camilla_config.yml"
TEST_SCRIPT = REPO_DIR / "scripts" / "test_audio.sh"
CDSP_WS_URL = "ws://localhost:1234"

# Home Assistant integration
HA_TOKEN_PATH = Path("/home/jaspertech/.ha_token")
HA_WS_URL = "ws://localhost:8123/api/websocket"
HA_API_BASE = "http://localhost:8123"
JASPER_PIPELINE_ID = "01km6zkgx2mskx0g09j4zztbrg"  # JasperVoice pipeline
JASPER_ENTITY_ID = "media_player.jasper"
VOICE_PE_ENTITY_ID = "media_player.home_assistant_voice_0a5232_media_player"
TTS_POLL_TIMEOUT = 9.0   # seconds to wait for Piper to finish generating
TTS_POLL_INTERVAL = 0.3  # polling cadence

# Room EQ
PROFILES_DIR = REPO_DIR / "audio" / "profiles"
CDSP_LIVE_CONFIG_PATH = Path("/home/jaspertech/.config/camilladsp/config.yml")
BASE_CONFIG_PATH = REPO_DIR / "audio" / "camilla_config.yml"
REW_TYPE_MAP = {
    "PK": "Peaking", "PEQ": "Peaking",
    "LS": "Lowshelf", "LSC": "Lowshelf",
    "HS": "Highshelf", "HSC": "Highshelf",
    "LP": "Lowpass", "LP6": "Lowpass",
    "HP": "Highpass", "HP6": "Highpass",
    "NO": "Notch", "AP": "Allpass",
}

SERVICES = {
    "alsa-loopback": "systemd",
    "camilladsp": "systemd",
    "squeezelite": "systemd",
    "music-assistant": "docker",
    "home-assistant": "docker",
}
DOCKER_CONTAINERS = {
    "music-assistant": "music-assistant",
    "home-assistant": "homeassistant",
}

ALLOWED_ACTIONS = {"start", "stop", "restart"}

MA_WS_URL = "ws://localhost:8095/ws"
MA_TOKEN_PATH = REPO_DIR / ".ma_token"
JASPER_PLAYER_NAME = os.environ.get("JASPER_PLAYER_NAME", "Jasper")
_resolved_player_id: Optional[str] = None


async def _ma_player_id() -> str:
    global _resolved_player_id
    if _resolved_player_id:
        return _resolved_player_id
    players = await _ma_command("players/all", {})
    match = next((p for p in players if p.get("name") == JASPER_PLAYER_NAME), None)
    if not match:
        raise HTTPException(404, detail=f"MA player '{JASPER_PLAYER_NAME}' not found — set JASPER_PLAYER_NAME env var")
    _resolved_player_id = match["player_id"]
    return _resolved_player_id

# Background tone subprocess
_tone_proc: Optional[subprocess.Popen] = None

# Volume saved before ducking
_pre_duck_volume: Optional[float] = None
_duck_restore_task: Optional[asyncio.Task] = None
DUCK_REDUCTION_DB = 20.0
DUCK_AUTO_RESTORE_S = 30.0


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_index():
    index = BASE_DIR / "index.html"
    return FileResponse(str(index), media_type="text/html")


# ---------------------------------------------------------------------------
# API: status
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def api_status():
    result = {}
    for svc, kind in SERVICES.items():
        if kind == "systemd":
            try:
                out = subprocess.check_output(
                    ["systemctl", "is-active", svc],
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                result[svc] = out  # "active" | "inactive" | "failed" | ...
            except subprocess.CalledProcessError as e:
                result[svc] = e.output.strip() if e.output else "inactive"
            except FileNotFoundError:
                result[svc] = "unavailable"
        else:
            container = DOCKER_CONTAINERS[svc]
            try:
                out = subprocess.check_output(
                    ["docker", "inspect", "--format", "{{.State.Status}}", container],
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
                result[svc] = out  # "running" | "exited" | ...
            except (subprocess.CalledProcessError, FileNotFoundError):
                result[svc] = "not found"
    return result


# ---------------------------------------------------------------------------
# API: ALSA
# ---------------------------------------------------------------------------

@app.get("/api/alsa")
async def api_alsa():
    try:
        raw = subprocess.check_output(
            ["aplay", "-l"], stderr=subprocess.DEVNULL, text=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"cards": [], "error": "aplay not available"}

    cards = []
    for line in raw.splitlines():
        m = re.match(r"^card (\d+): (\S+) \[([^\]]+)\]", line)
        if m:
            cards.append({
                "index": int(m.group(1)),
                "id": m.group(2),
                "name": m.group(3),
            })
    return {"cards": cards}


# ---------------------------------------------------------------------------
# API: CamillaDSP config
# ---------------------------------------------------------------------------

@app.get("/api/cdsp/config")
async def api_cdsp_config():
    if not CONFIG_PATH.exists():
        raise HTTPException(404, detail="camilla_config.yml not found")
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    samplerate = cfg.get("devices", {}).get("samplerate", "unknown")

    # Find crossover freq + filter type from first LP filter
    filters = cfg.get("filters", {})
    crossover_freq = 2500
    filter_type = "LinkwitzRiley"
    filter_order = 4
    for _name, fdef in filters.items():
        params = fdef.get("parameters", {})
        if "freq" in params:
            crossover_freq = params["freq"]
            ft = params.get("type", "")
            if "Lowpass" in ft or "Highpass" in ft:
                filter_type = re.sub(r"(Lowpass|Highpass)", "", ft).strip()
            order = params.get("order")
            if order:
                filter_order = order
            break

    return {
        "samplerate": samplerate,
        "crossover_freq": crossover_freq,
        "filter_type": filter_type,
        "filter_order": filter_order,
        "capture_device": cfg.get("devices", {}).get("capture", {}).get("device"),
        "playback_device": cfg.get("devices", {}).get("playback", {}).get("device"),
    }


# ---------------------------------------------------------------------------
# API: service control
# ---------------------------------------------------------------------------

@app.post("/api/services/{svc}/{action}")
async def api_service_control(svc: str, action: str):
    if svc not in SERVICES:
        raise HTTPException(400, detail=f"Unknown service: {svc}")
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(400, detail=f"Action must be one of {ALLOWED_ACTIONS}")

    kind = SERVICES[svc]
    try:
        if kind == "systemd":
            subprocess.check_call(
                ["sudo", "systemctl", action, svc],
                stderr=subprocess.DEVNULL,
            )
        else:
            container = DOCKER_CONTAINERS[svc]
            subprocess.check_call(
                ["docker", action, container],
                stderr=subprocess.DEVNULL,
            )
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, detail=f"Command failed (exit {e.returncode})")

    return {"ok": True, "service": svc, "action": action}


# ---------------------------------------------------------------------------
# API: test stream (SSE)
# ---------------------------------------------------------------------------

@app.get("/api/test/run")
async def api_test_run():
    if not TEST_SCRIPT.exists():
        async def missing():
            yield "data: ERROR: test_audio.sh not found\n\n"
        return StreamingResponse(missing(), media_type="text/event-stream")

    async def stream_output():
        proc = await asyncio.create_subprocess_exec(
            "bash", str(TEST_SCRIPT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            text = line.decode(errors="replace").rstrip()
            yield f"data: {text}\n\n"
        await proc.wait()
        yield "data: [done]\n\n"

    return StreamingResponse(
        stream_output(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Music Assistant helpers
# ---------------------------------------------------------------------------

async def _ma_command(command: str, args: dict) -> dict:
    """Send one authenticated command to Music Assistant and return result."""
    token = MA_TOKEN_PATH.read_text().strip()
    async with websockets.connect(MA_WS_URL) as ws:
        await ws.recv()  # server info
        await ws.send(json.dumps({"message_id": 1, "command": "auth", "args": {"token": token}}))
        auth = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        if not auth.get("result", {}).get("authenticated"):
            raise HTTPException(503, detail="MA auth failed")
        await ws.send(json.dumps({"message_id": 2, "command": command, "args": args}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    if "error_code" in resp:
        raise HTTPException(502, detail=f"MA error {resp['error_code']}: {resp.get('details')}")
    return resp.get("result", {})


class PlayRequest(BaseModel):
    query: str
    media_type: str = "playlist"  # playlist | track | artist | album | radio


@app.post("/api/ma/play")
async def api_ma_play(req: PlayRequest):
    """Search MA and play top result on the Jasper player."""
    results = await _ma_command("music/search", {
        "search_query": req.query,
        "media_types": [req.media_type],
        "limit": 5,
    })
    items = results.get(req.media_type + "s", []) or results.get("tracks", [])
    if not items:
        # Fallback: search across all types
        results = await _ma_command("music/search", {
            "search_query": req.query,
            "limit": 5,
        })
        for key in ("playlists", "tracks", "artists", "albums", "radio"):
            if results.get(key):
                items = results[key]
                break
    if not items:
        raise HTTPException(404, detail=f"No results found for: {req.query}")
    uri = items[0].get("uri") or items[0].get("item_id")
    pid = await _ma_player_id()
    await _ma_command("player_queues/play_media", {
        "queue_id": pid,
        "media": uri,
        "option": "replace",
    })
    return {"ok": True, "playing": items[0].get("name"), "uri": uri}


@app.post("/api/ma/pause")
async def api_ma_pause():
    await _ma_command("player_queues/pause", {"queue_id": await _ma_player_id()})
    return {"ok": True}


@app.post("/api/ma/resume")
async def api_ma_resume():
    await _ma_command("player_queues/play", {"queue_id": await _ma_player_id()})
    return {"ok": True}


@app.post("/api/ma/next")
async def api_ma_next():
    await _ma_command("player_queues/next", {"queue_id": await _ma_player_id()})
    return {"ok": True}


@app.post("/api/ma/previous")
async def api_ma_previous():
    await _ma_command("player_queues/previous", {"queue_id": await _ma_player_id()})
    return {"ok": True}


class VolumeRequest(BaseModel):
    level: int  # 0–100


@app.post("/api/ma/volume")
async def api_ma_volume(req: VolumeRequest):
    await _ma_command("players/cmd/volume_set", {
        "player_id": await _ma_player_id(),
        "volume_level": max(0, min(100, req.level)),
    })
    return {"ok": True, "volume": req.level}


@app.get("/api/ma/status")
async def api_ma_status():
    try:
        pid = await _ma_player_id()
        players = await _ma_command("players/all", {})
        player = next((p for p in players if p.get("player_id") == pid), None)
        queue = await _ma_command("player_queues/get", {"queue_id": pid})
        current_item = queue.get("current_item") or {}
        media = current_item.get("media_item") or {}
        artists = media.get("artists") or []
        artist_name = artists[0].get("name") if artists else media.get("artist", "")
        return {
            "state": player.get("state") if player else "unavailable",
            "volume": round((player.get("volume_level") or 0)),
            "title": media.get("name") or queue.get("display_name") or "",
            "artist": artist_name,
            "album": (media.get("album") or {}).get("name", ""),
            "image": media.get("image", {}).get("path") if media.get("image") else None,
            "shuffle": queue.get("shuffle_enabled", False),
            "repeat": queue.get("repeat_mode", "off"),
        }
    except Exception as e:
        return {"state": "unavailable", "error": str(e)}


# ---------------------------------------------------------------------------
# API: audio ducking (called by HA automations on TTS start/end)
# ---------------------------------------------------------------------------

async def _cdsp_get_volume() -> float:
    async with websockets.connect(CDSP_WS_URL) as ws:
        await ws.send(json.dumps({"GetVolume": None}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
        return resp["GetVolume"]["value"]


async def _cdsp_set_volume(db: float) -> None:
    async with websockets.connect(CDSP_WS_URL) as ws:
        await ws.send(json.dumps({"SetVolume": db}))
        await asyncio.wait_for(ws.recv(), timeout=3)


async def _auto_restore_duck():
    await asyncio.sleep(DUCK_AUTO_RESTORE_S)
    global _pre_duck_volume, _duck_restore_task
    if _pre_duck_volume is not None:
        try:
            await _cdsp_set_volume(_pre_duck_volume)
        except Exception:
            pass
        _pre_duck_volume = None
    _duck_restore_task = None


@app.get("/api/duck/status")
async def api_duck_status():
    return {"ducked": _pre_duck_volume is not None, "saved_volume": _pre_duck_volume}


@app.post("/api/duck/start")
async def api_duck_start():
    global _pre_duck_volume, _duck_restore_task
    if _duck_restore_task and not _duck_restore_task.done():
        _duck_restore_task.cancel()
    try:
        _pre_duck_volume = await _cdsp_get_volume()
        await _cdsp_set_volume(_pre_duck_volume - DUCK_REDUCTION_DB)
    except Exception as e:
        raise HTTPException(503, detail=f"CamillaDSP unavailable: {e}")
    _duck_restore_task = asyncio.create_task(_auto_restore_duck())
    return {"ok": True, "was": _pre_duck_volume, "now": _pre_duck_volume - DUCK_REDUCTION_DB}


@app.post("/api/duck/end")
async def api_duck_end():
    global _pre_duck_volume, _duck_restore_task
    if _duck_restore_task and not _duck_restore_task.done():
        _duck_restore_task.cancel()
    _duck_restore_task = None
    try:
        target = _pre_duck_volume if _pre_duck_volume is not None else 0.0
        await _cdsp_set_volume(target)
        _pre_duck_volume = None
    except Exception as e:
        raise HTTPException(503, detail=f"CamillaDSP unavailable: {e}")
    return {"ok": True, "restored_to": target}


# ---------------------------------------------------------------------------
# API: tone generator
# ---------------------------------------------------------------------------

@app.post("/api/tone/start")
async def api_tone_start(freq: int = 1000):
    global _tone_proc
    if _tone_proc and _tone_proc.poll() is None:
        _tone_proc.terminate()
    _tone_proc = subprocess.Popen(
        [
            "speaker-test",
            "-D", "hw:Loopback,0",
            "-t", "sine",
            "-f", str(freq),
            "-c", "2",
            "-l", "0",  # loop forever
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "freq": freq, "pid": _tone_proc.pid}


@app.post("/api/tone/stop")
async def api_tone_stop():
    global _tone_proc
    if _tone_proc and _tone_proc.poll() is None:
        _tone_proc.terminate()
        _tone_proc = None
        return {"ok": True, "stopped": True}
    return {"ok": True, "stopped": False}


# ---------------------------------------------------------------------------
# Helpers: CamillaDSP config get/set
# ---------------------------------------------------------------------------

async def _cdsp_get_config() -> dict:
    """Return live CamillaDSP config as a parsed dict."""
    async with websockets.connect(CDSP_WS_URL) as ws:
        await ws.send(json.dumps({"GetConfig": None}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        result = resp.get("GetConfig", {})
        if result.get("result") != "Ok":
            raise HTTPException(503, detail="CamillaDSP unavailable")
        return yaml.safe_load(result["value"]) or {}


def _config_to_yaml(cfg: dict) -> str:
    """Serialise config dict back to YAML, stripping None values CamillaDSP added."""
    def _strip_none(obj):
        if isinstance(obj, dict):
            return {k: _strip_none(v) for k, v in obj.items() if v is not None}
        if isinstance(obj, list):
            return [_strip_none(i) for i in obj]
        return obj
    return yaml.dump(_strip_none(cfg), default_flow_style=False, allow_unicode=True, sort_keys=False)


async def _cdsp_apply_config(cfg: dict) -> None:
    """Apply config dict live via WebSocket and persist to disk."""
    cfg_yaml = _config_to_yaml(cfg)
    async with websockets.connect(CDSP_WS_URL) as ws:
        await ws.send(json.dumps({"SetConfig": cfg_yaml}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        result = resp.get("SetConfig", {})
        if result.get("result") != "Ok":
            raise HTTPException(502, detail=f"CamillaDSP SetConfig failed: {result}")
    CDSP_LIVE_CONFIG_PATH.write_text(cfg_yaml)


def _parse_rew_filters(text: str) -> list[dict]:
    """Parse REW 'Filter Settings' parametric EQ export → list of filter param dicts."""
    results = []
    pattern = re.compile(
        r"Filter\s+\d+:\s+(ON|OFF)\s+(\w+)\s+Fc\s+([\d.]+)\s+Hz\s+Gain\s+([-\d.]+)\s+dB\s+Q\s+([\d.]+)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        enabled, ftype, freq, gain, q = m.groups()
        if enabled.upper() != "ON":
            continue
        cdsp_type = REW_TYPE_MAP.get(ftype.upper())
        if not cdsp_type:
            continue
        results.append({
            "cdsp_type": cdsp_type,
            "freq": float(freq),
            "gain": float(gain),
            "q": float(q),
        })
    return results


def _apply_rew_to_config(cfg: dict, rew_filters: list[dict]) -> dict:
    """Add REW filters to config dict, replacing any existing rew_* entries."""
    cfg = copy.deepcopy(cfg)
    filters = cfg.setdefault("filters", {})

    # Remove old rew_* filters
    for k in [k for k in filters if k.startswith("rew_")]:
        del filters[k]

    new_names: list[str] = []
    for i, f in enumerate(rew_filters, 1):
        name = f"rew_{i}"
        params: dict = {"type": f["cdsp_type"], "freq": f["freq"]}
        if f["cdsp_type"] in ("Peaking", "Notch", "Allpass"):
            params["gain"] = f["gain"]
            params["q"] = f["q"]
        elif f["cdsp_type"] in ("Lowshelf", "Highshelf"):
            params["gain"] = f["gain"]
            params["q"] = f["q"]
        else:  # Lowpass, Highpass
            params["q"] = f["q"]
        filters[name] = {"type": "Biquad", "parameters": params}
        new_names.append(name)

    for step in cfg.get("pipeline", []):
        if step.get("type") == "Filter":
            existing = [n for n in (step.get("names") or []) if not n.startswith("rew_")]
            step["names"] = existing + new_names

    return cfg


# ---------------------------------------------------------------------------
# API: Room EQ — profiles
# ---------------------------------------------------------------------------

@app.get("/api/eq/profiles")
async def api_eq_profiles():
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return {"profiles": sorted(p.stem for p in PROFILES_DIR.glob("*.yml"))}


@app.post("/api/eq/profiles/{name}")
async def api_eq_profile_save(name: str):
    if not re.match(r"^[\w\-]+$", name):
        raise HTTPException(400, detail="Profile name: alphanumeric/dash/underscore only")
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    cfg = await _cdsp_get_config()
    (PROFILES_DIR / f"{name}.yml").write_text(_config_to_yaml(cfg))
    return {"ok": True, "saved": name}


@app.post("/api/eq/profiles/{name}/load")
async def api_eq_profile_load(name: str):
    path = PROFILES_DIR / f"{name}.yml"
    if not path.exists():
        raise HTTPException(404, detail=f"Profile '{name}' not found")
    cfg = yaml.safe_load(path.read_text()) or {}
    await _cdsp_apply_config(cfg)
    return {"ok": True, "loaded": name}


@app.delete("/api/eq/profiles/{name}")
async def api_eq_profile_delete(name: str):
    path = PROFILES_DIR / f"{name}.yml"
    if not path.exists():
        raise HTTPException(404, detail=f"Profile '{name}' not found")
    path.unlink()
    return {"ok": True, "deleted": name}


# ---------------------------------------------------------------------------
# API: Room EQ — import + filters
# ---------------------------------------------------------------------------

@app.post("/api/eq/import/rew")
async def api_eq_import_rew(file: UploadFile = File(...)):
    """Parse an REW 'Filter Settings' text export and apply to CamillaDSP."""
    text = (await file.read()).decode("utf-8", errors="replace")
    rew_filters = _parse_rew_filters(text)
    if not rew_filters:
        raise HTTPException(400, detail="No enabled filters found — export from REW as 'Filter Settings' text")
    cfg = await _cdsp_get_config()
    cfg = _apply_rew_to_config(cfg, rew_filters)
    await _cdsp_apply_config(cfg)
    return {"ok": True, "applied": len(rew_filters), "filters": rew_filters}


@app.get("/api/eq/filters")
async def api_eq_filters():
    """Return all active biquad filters from the live CamillaDSP config."""
    cfg = await _cdsp_get_config()
    result = []
    for name, fdef in (cfg.get("filters") or {}).items():
        if not isinstance(fdef, dict):
            continue
        params = fdef.get("parameters") or {}
        result.append({
            "name": name,
            "type": fdef.get("type"),
            "subtype": params.get("type"),
            "freq": params.get("freq"),
            "gain": params.get("gain"),
            "q": params.get("q"),
            "is_rew": name.startswith("rew_"),
        })
    return {"filters": result}


@app.post("/api/eq/reset")
async def api_eq_reset():
    """Remove all REW filters and restore the committed base config."""
    if not BASE_CONFIG_PATH.exists():
        raise HTTPException(404, detail="Base config not found at audio/camilla_config.yml")
    cfg = yaml.safe_load(BASE_CONFIG_PATH.read_text()) or {}
    await _cdsp_apply_config(cfg)
    return {"ok": True}


@app.get("/api/system/boot_time")
async def api_boot_time():
    """Return systemd-analyze output for boot timing."""
    try:
        out = subprocess.check_output(["systemd-analyze"], text=True, stderr=subprocess.DEVNULL).strip()
        blame = subprocess.check_output(
            ["systemd-analyze", "blame", "--no-pager"],
            text=True, stderr=subprocess.DEVNULL
        ).strip().splitlines()[:10]
        return {"ok": True, "summary": out, "top_units": blame}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# API: TTS bridge — polls HA pipeline debug for TTS URL, plays on Jasper
# ---------------------------------------------------------------------------

async def _ha_ws_connect():
    """Open an authenticated HA WebSocket connection. Returns ws handle."""
    token = HA_TOKEN_PATH.read_text().strip()
    ws = await websockets.connect(HA_WS_URL, open_timeout=5)
    hello = json.loads(await ws.recv())
    if hello.get("type") != "auth_required":
        await ws.close()
        raise HTTPException(503, detail="HA WS unexpected hello")
    await ws.send(json.dumps({"type": "auth", "access_token": token}))
    auth_ok = json.loads(await ws.recv())
    if auth_ok.get("type") != "auth_ok":
        await ws.close()
        raise HTTPException(503, detail=f"HA WS auth failed: {auth_ok.get('type')}")
    return ws


async def _ha_ws_cmd(ws, msg_id: int, msg_type: str, **kwargs) -> dict:
    """Send one HA WebSocket command, return matching result message."""
    payload = {"id": msg_id, "type": msg_type, **kwargs}
    await ws.send(json.dumps(payload))
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == msg_id:
            return resp


@app.post("/api/tts_bridge")
async def api_tts_bridge():
    """
    Called by HA automation when satellite enters 'responding'.
    Polls HA's pipeline debug API until Piper has generated TTS, then plays
    the URL on media_player.jasper with announce=True so MA ducks & resumes.
    """
    tts_url: Optional[str] = None
    logger.info("TTS bridge: invoked")

    try:
        async with asyncio.timeout(TTS_POLL_TIMEOUT + 3):
            ws = await _ha_ws_connect()
            try:
                msg_id = 1

                # 1. Find the most recent run ID for the JasperVoice pipeline.
                #    HA registers runs at pipeline start, so the current run is
                #    already in the list by the time 'responding' fires.
                latest_run_id: Optional[str] = None
                loop = asyncio.get_running_loop()
                deadline = loop.time() + TTS_POLL_TIMEOUT
                while loop.time() < deadline and latest_run_id is None:
                    resp = await _ha_ws_cmd(ws, msg_id,
                                            "assist_pipeline/pipeline_debug/list",
                                            pipeline_id=JASPER_PIPELINE_ID)
                    msg_id += 1
                    runs = resp.get("result", {}).get("pipeline_runs", [])
                    if runs:
                        latest_run_id = runs[-1]["pipeline_run_id"]
                        logger.info("TTS bridge: run %s (%d total)", latest_run_id, len(runs))
                    else:
                        await asyncio.sleep(TTS_POLL_INTERVAL)

                if not latest_run_id:
                    logger.error("TTS bridge: no runs found")
                    raise HTTPException(504, detail="No pipeline runs found for JasperVoice")

                # 2. Poll the run's events until tts-end appears
                while loop.time() < deadline:
                    resp = await _ha_ws_cmd(ws, msg_id,
                                            "assist_pipeline/pipeline_debug/get",
                                            pipeline_id=JASPER_PIPELINE_ID,
                                            pipeline_run_id=latest_run_id)
                    msg_id += 1
                    for event in reversed(resp.get("result", {}).get("events", [])):
                        if event.get("type") == "tts-end":
                            out = event.get("data", {}).get("tts_output") or {}
                            if out.get("url"):
                                tts_url = out["url"]
                                break
                    if tts_url:
                        break
                    await asyncio.sleep(TTS_POLL_INTERVAL)

                if not tts_url:
                    logger.error("TTS bridge: tts-end not found within %ss for run %s",
                                 TTS_POLL_TIMEOUT, latest_run_id)
                    raise HTTPException(504, detail="TTS not ready within timeout")

                # 3. Make URL absolute so MA/Squeezelite can fetch it
                if tts_url.startswith("/"):
                    tts_url = f"{HA_API_BASE}{tts_url}"
                logger.info("TTS bridge: playing %s", tts_url)

                # 4. Play on Jasper (announce=True: MA ducks music and resumes)
                await _ha_ws_cmd(ws, msg_id, "call_service",
                                 domain="media_player",
                                 service="play_media",
                                 target={"entity_id": JASPER_ENTITY_ID},
                                 service_data={
                                     "media_content_id": tts_url,
                                     "media_content_type": "music",
                                     "announce": True,
                                 })
                logger.info("TTS bridge: play_media dispatched")
            finally:
                await ws.close()

    except HTTPException:
        raise
    except TimeoutError:
        logger.error("TTS bridge: timed out")
        raise HTTPException(504, detail="TTS bridge timed out")
    except Exception as e:
        logger.error("TTS bridge: error: %s", e)
        raise HTTPException(502, detail=f"TTS bridge error: {e}")

    return {"ok": True, "tts_url": tts_url}


# ---------------------------------------------------------------------------
# WebSocket: CamillaDSP proxy
# ---------------------------------------------------------------------------

@app.websocket("/ws/cdsp")
async def ws_cdsp_proxy(ws: WebSocket):
    await ws.accept()
    try:
        async with websockets.connect(CDSP_WS_URL) as cdsp_ws:

            async def browser_to_cdsp():
                try:
                    while True:
                        data = await ws.receive_text()
                        await cdsp_ws.send(data)
                except (WebSocketDisconnect, Exception):
                    pass

            async def cdsp_to_browser():
                try:
                    async for msg in cdsp_ws:
                        if ws.client_state == WebSocketState.CONNECTED:
                            await ws.send_text(msg)
                        else:
                            break
                except Exception:
                    pass

            await asyncio.gather(browser_to_cdsp(), cdsp_to_browser())

    except (OSError, websockets.exceptions.WebSocketException) as e:
        # CamillaDSP not running — send error and close cleanly
        try:
            await ws.send_text(f'{{"error": "cdsp unavailable: {e}"}}')
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
