import asyncio
import json
import time

import httpx

from ..core.providers import (
    AIProvider,
    CameraProvider,
    Detection,
    Frame,
    NotificationProvider,
    VisionProvider,
    VoiceSatellite,
)


class TestCamera(CameraProvider):
    __test__ = False

    def __init__(self):
        self.connected = True
        self.started = time.time()

    async def frames(self):
        while True:
            yield Frame(None, time.time(), 1280, 720)
            await asyncio.sleep(0.5)

    async def snapshot(self, high_quality=True):
        return Frame(
            None,
            time.time(),
            1920 if high_quality else 640,
            1080 if high_quality else 360,
        )

    def health(self):
        return {"status": "ready", "mode": "test", "connected": True}


class TapoCamera(CameraProvider):
    def __init__(self, sub_url, main_url):
        self.sub_url = sub_url
        self.main_url = main_url
        self.connected = False
        self.reconnects = 0
        self.last_frame = None
        self.last_image = None
        self.frame_count = 0
        self.stream_started = None

    async def frames(self):
        try:
            import cv2
        except ImportError:
            return
        delay = 1
        while True:
            cap = cv2.VideoCapture(self.sub_url, cv2.CAP_FFMPEG)
            self.connected = cap.isOpened()
            if self.connected:
                self.stream_started = time.time()
                delay = 1
            while self.connected:
                ok, img = await asyncio.to_thread(cap.read)
                if not ok:
                    break
                self.last_frame = time.time()
                self.last_image = img
                self.frame_count += 1
                h, w = img.shape[:2]
                yield Frame(img, self.last_frame, w, h)
            self.connected = False
            cap.release()
            self.reconnects += 1
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def snapshot(self, high_quality=True):
        try:
            import cv2
        except ImportError:
            return None
        url = self.main_url if high_quality else self.sub_url
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        ok, img = await asyncio.to_thread(cap.read)
        cap.release()
        if not ok:
            return None
        h, w = img.shape[:2]
        return Frame(img, time.time(), w, h)

    def health(self):
        return {
            "status": "connected" if self.connected else "disconnected",
            "connected": self.connected,
            "last_frame": self.last_frame,
            "reconnects": self.reconnects,
            "stream_fps": round(
                self.frame_count / max(time.time() - self.stream_started, 0.001), 2
            )
            if self.stream_started
            else 0,
            "main_configured": bool(self.main_url),
            "sub_configured": bool(self.sub_url),
        }


class MockVision(VisionProvider):
    async def detect(self, frame):
        return []


class YoloVision(VisionProvider):
    def __init__(self, model, confidence):
        from ultralytics import YOLO

        self.model = YOLO(model)
        self.confidence = confidence

    async def detect(self, frame):
        result = (
            await asyncio.to_thread(
                self.model.predict,
                frame.data,
                classes=[0],
                conf=self.confidence,
                verbose=False,
            )
        )[0]
        out = []
        for b in result.boxes:
            x1, y1, x2, y2 = map(float, b.xyxyn[0])
            out.append(
                Detection(
                    "person",
                    float(b.conf[0]),
                    (x1, y1, x2, y2),
                    int(b.id[0]) if b.id is not None else None,
                )
            )
        return out


class OllamaAI(AIProvider):
    def __init__(self, url, model):
        self.url = url.rstrip("/")
        self.model = model

    async def health(self):
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(self.url + "/api/tags")
            names = [m.get("name") for m in r.json().get("models", [])]
            return {
                "status": "ready" if self.model in names else "model_missing",
                "model": self.model,
                "available": names,
            }
        except Exception as e:  # noqa: BLE001 - health checks normalize transport/JSON failures
            return {
                "status": "unavailable",
                "model": self.model,
                "detail": type(e).__name__,
            }

    async def respond(self, system, messages, state):
        prompt = messages + [
            {
                "role": "user",
                "content": "Authoritative structured state: " + json.dumps(state),
            }
        ]
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(
                self.url + "/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "format": "json",
                    "think": False,
                    "keep_alive": "10m",
                    "options": {"temperature": 0.1, "num_predict": 160},
                    "messages": [{"role": "system", "content": system}] + prompt,
                },
            )
            r.raise_for_status()
        return json.loads(r.json()["message"]["content"])


class SimulatorVoice(VoiceSatellite):
    def __init__(self):
        self.last_spoken = ""

    async def speak(self, text):
        self.last_spoken = text

    def health(self):
        return {
            "status": "ready",
            "provider": "simulator",
            "last_spoken": self.last_spoken,
        }


class LogNotification(NotificationProvider):
    def __init__(self, bus):
        self.bus = bus

    async def send(self, title, body, image_path=None):
        self.bus.publish(
            "notification.sent",
            {"title": title, "body": body, "image_path": image_path},
        )
