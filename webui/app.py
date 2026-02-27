"""
jasper-speaker Web Dashboard — FastAPI backend
Serves on port 8080, proxies CamillaDSP WS, exposes system control endpoints.
"""

import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

import yaml
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
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

# Background tone subprocess
_tone_proc: Optional[subprocess.Popen] = None


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
