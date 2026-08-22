#!/usr/bin/env python3
from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from jarvis_home.config import get_settings


def result(ok: bool, label: str, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f": {detail}" if detail else ""))


def probe(url: str, label: str) -> tuple[bool, dict]:
    if not url:
        result(False, label, "not configured")
        return False, {}
    command = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "5000000",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        url,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=10, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        result(False, label, type(error).__name__)
        return False, {}
    if completed.returncode:
        result(False, label, "authentication, network, or stream error")
        return False, {}
    data = json.loads(completed.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    detail = f"{stream.get('codec_name', '?')} {stream.get('width', '?')}x{stream.get('height', '?')} @ {stream.get('avg_frame_rate', '?')}"
    result(True, label, detail)
    return True, stream


def snapshot(url: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="jarvis-camera-test-") as directory:
        target = Path(directory) / "snapshot.jpg"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-i",
            url,
            "-frames:v",
            "1",
            "-y",
            str(target),
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, timeout=12, check=False
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            result(False, "Main-stream snapshot", type(error).__name__)
            return False
        ok = (
            completed.returncode == 0
            and target.exists()
            and target.stat().st_size > 1000
        )
        result(
            ok,
            "Main-stream snapshot",
            f"decoded {target.stat().st_size} bytes" if ok else "decode failed",
        )
        return ok


def main() -> int:
    cfg = get_settings()
    if not cfg.camera_host and not (
        cfg.camera_rtsp_url_main or cfg.camera_rtsp_url_sub
    ):
        result(False, "Credentials", "run ./scripts/configure-tapo.sh")
        return 1
    if cfg.camera_host:
        try:
            with socket.create_connection((cfg.camera_host, 554), timeout=3):
                result(True, "Host TCP/554 reachable")
        except OSError:
            result(False, "Host TCP/554 reachable")
    main_ok, _ = probe(cfg.rtsp_url(True), "RTSP main stream")
    sub_ok, _ = probe(cfg.rtsp_url(False), "RTSP sub stream")
    snap_ok = snapshot(cfg.rtsp_url(True)) if main_ok else False
    reconnect_ok, _ = (
        probe(cfg.rtsp_url(False), "Reconnect after clean close")
        if sub_ok
        else (False, {})
    )
    result(reconnect_ok, "Reconnect behavior")
    return 0 if main_ok and sub_ok and snap_ok and reconnect_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
