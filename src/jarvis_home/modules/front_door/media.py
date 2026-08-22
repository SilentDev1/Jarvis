from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class OCRResult:
    text: str
    confidence: float
    name_candidate: str | None = None
    company_candidate: str | None = None


def sharpness(image) -> float:
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def select_sharpest(images):
    if not images:
        return None, 0.0
    scored = [(sharpness(image), image) for image in images]
    return max(scored, key=lambda item: item[0])[1], max(item[0] for item in scored)


def parse_badge_candidates(text: str) -> tuple[str | None, str | None]:
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 2]
    company_words = (
        "comcast",
        "xfinity",
        "verizon",
        "spectrum",
        "amazon",
        "ups",
        "fedex",
    )
    company = next(
        (line for line in lines if any(w in line.lower() for w in company_words)), None
    )
    name = next(
        (
            line
            for line in lines
            if line != company
            and re.fullmatch(r"[A-Za-z][A-Za-z .'-]{2,60}", line)
            and len(line.split()) in {2, 3}
        ),
        None,
    )
    return name, company


async def run_ocr(image) -> OCRResult:
    import cv2
    import pytesseract
    from pytesseract import Output

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    enhanced = cv2.convertScaleAbs(gray, alpha=1.35, beta=5)
    data = await asyncio.to_thread(
        pytesseract.image_to_data, enhanced, config="--psm 6", output_type=Output.DICT
    )
    words = []
    confidences = []
    for word, confidence in zip(data["text"], data["conf"], strict=True):
        word = word.strip()
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            continue
        if word and score >= 0:
            words.append(word)
            confidences.append(score)
    text = " ".join(words)
    name, company = parse_badge_candidates(text)
    return OCRResult(
        text, sum(confidences) / len(confidences) if confidences else 0, name, company
    )


def save_jpeg(image, path: Path) -> Path:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), image):
        raise ValueError("OpenCV could not encode image")
    return path


async def capture_burst(camera, seconds=3.0, interval=0.35):
    frames = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        frame = await camera.snapshot(high_quality=True)
        if frame is not None and frame.data is not None:
            frames.append(frame.data)
        await asyncio.sleep(interval)
    return frames
