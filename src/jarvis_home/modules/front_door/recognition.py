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
        self.detector = cv2.FaceDetectorYN.create(str(detector_model), "", (320, 320), 0.8, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_model), "")
        self.threshold = threshold
        self.possible_threshold = min(possible_threshold, threshold)
        self.last_face_count = 0

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

    def match(self, embedding: np.ndarray, candidates: list[tuple[int, str, Path]]) -> FaceMatch | None:
        best = None
        for known_id, name, path in candidates:
            try:
                known = np.load(path, allow_pickle=False).flatten().astype(np.float32)
            except (OSError, ValueError):
                continue
            score = float(np.dot(embedding, known) / (np.linalg.norm(embedding) * np.linalg.norm(known)))
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
