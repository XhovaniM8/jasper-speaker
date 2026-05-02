"""
jasper-speaker Web Dashboard — FastAPI backend
Serves on port 8080, proxies CamillaDSP WS, exposes system control endpoints.
"""

import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

import yaml
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.websockets import WebSocketState

app = FastAPI(title="Jasper Speaker Dashboard")

BASE_DIR = Path(__file__).parent
REPO_DIR = BASE_DIR.parent
CONFIG_PATH = REPO_DIR / "audio" / "camilla_config.yml"
TEST_SCRIPT = REPO_DIR / "scripts" / "test_audio.sh"
CDSP_WS_URL = "ws://localhost:1234"

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
