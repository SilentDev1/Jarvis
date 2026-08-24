from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


@dataclass
class FaceMatch:
    known_person_id: int
    display_name: str
    confidence: float
    status: str = "KNOWN_HIGH_CONFIDENCE"


@dataclass
class FaceCandidate:
    crop: object
    confidence: float
    quality_score: float
    face_count: int
    ambiguous: bool = False


class FaceRecognitionProvider(Protocol):
    def embedding(self, image) -> np.ndarray | None: ...
    def match(self, embedding, candidates) -> FaceMatch | None: ...
    def save_embedding(self, embedding, path: Path) -> None: ...


class DisabledFaceRecognitionProvider:
    def embedding(self, image) -> None:
        return None

    def match(self, embedding, candidates) -> None:
        return None

    def save_embedding(self, embedding, path: Path) -> None:
        raise RuntimeError("Face recognition is disabled")


class OpenCVFaceRecognition:
    """Local YuNet/SFace embedding provider; matches are identity hints, not authentication."""

    def __init__(
        self,
        detector_model: Path,
        recognizer_model: Path,
        threshold=0.45,
        possible_threshold=0.36,
    ):
        import cv2

        if not detector_model.exists() or not recognizer_model.exists():
            raise FileNotFoundError("YuNet/SFace model files are missing")
        self.cv2 = cv2
        self.detector = cv2.FaceDetectorYN.create(
            str(detector_model), "", (320, 320), 0.8, 0.3, 5000
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_model), "")
        self.threshold = threshold
        self.possible_threshold = min(possible_threshold, threshold)
        self.last_face_count = 0

    def candidate(self, image, padding=0.35) -> FaceCandidate | None:
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _retval, faces = self.detector.detect(image)
        self.last_face_count = 0 if faces is None else len(faces)
        if faces is None or len(faces) == 0:
            return None
        ranked = sorted(faces, key=lambda item: float(item[2] * item[3]), reverse=True)
        ambiguous = (
            len(ranked) > 1
            and ranked[1][2] * ranked[1][3] >= ranked[0][2] * ranked[0][3] * 0.65
        )
        face = ranked[0]
        x, y, w, h = map(float, face[:4])
        pad_x, pad_y = w * padding, h * padding
        x1, y1 = max(0, int(x - pad_x)), max(0, int(y - pad_y))
        x2, y2 = min(width, int(x + w + pad_x)), min(height, int(y + h + pad_y))
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        sharp = float(self.cv2.Laplacian(crop, self.cv2.CV_64F).var())
        brightness = float(self.cv2.cvtColor(crop, self.cv2.COLOR_BGR2GRAY).mean())
        exposure = max(0.0, 1.0 - abs(brightness - 128.0) / 128.0)
        area_ratio = min(1.0, (w * h) / max(width * height * 0.08, 1))
        confidence = float(face[14]) if len(face) > 14 else 0.8
        quality = (
            min(100.0, sharp / 4) * 0.45
            + area_ratio * 30
            + exposure * 15
            + confidence * 10
        )
        return FaceCandidate(
            crop, confidence, round(quality, 2), len(ranked), ambiguous
        )

    def embedding(self, image) -> np.ndarray | None:
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _retval, faces = self.detector.detect(image)
        self.last_face_count = 0 if faces is None else len(faces)
        if faces is None or len(faces) == 0:
            return None
        # Avoid assigning one identity when a group makes the primary visitor ambiguous.
        if len(faces) > 1:
            areas = sorted((float(face[2] * face[3]) for face in faces), reverse=True)
            if areas[1] >= areas[0] * 0.65:
                return None
        face = max(faces, key=lambda item: float(item[2] * item[3]))
        if face[2] < 80 or face[3] < 80:
            return None
        aligned = self.recognizer.alignCrop(image, face)
        if self.cv2.Laplacian(aligned, self.cv2.CV_64F).var() < 35:
            return None
        feature = self.recognizer.feature(aligned).flatten().astype(np.float32)
        norm = float(np.linalg.norm(feature))
        return feature / norm if norm else None

    def match(
        self, embedding: np.ndarray, candidates: list[tuple[int, str, Path]]
    ) -> FaceMatch | None:
        best = None
        for known_id, name, path in candidates:
            try:
                known = np.load(path, allow_pickle=False).flatten().astype(np.float32)
            except (OSError, ValueError):
                continue
            score = float(
                np.dot(embedding, known)
                / (np.linalg.norm(embedding) * np.linalg.norm(known))
            )
            if best is None or score > best.confidence:
                best = FaceMatch(known_id, name, score)
        if best and best.confidence >= self.threshold:
            best.status = "KNOWN_HIGH_CONFIDENCE"
            return best
        if best and best.confidence >= self.possible_threshold:
            best.status = "POSSIBLE_MATCH"
            return best
        return None

    def save_embedding(self, embedding: np.ndarray, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, embedding.astype(np.float32), allow_pickle=False)
