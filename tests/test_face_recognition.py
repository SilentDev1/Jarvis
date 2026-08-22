from pathlib import Path

import numpy as np

from jarvis_home.modules.front_door.recognition import (
    DisabledFaceRecognitionProvider,
    OpenCVFaceRecognition,
)


def provider(high=0.8, possible=0.6):
    instance = OpenCVFaceRecognition.__new__(OpenCVFaceRecognition)
    instance.threshold = high
    instance.possible_threshold = possible
    return instance


def candidate(tmp_path: Path, vector, name="Mike"):
    path = tmp_path / "face.npy"
    np.save(path, np.asarray(vector, dtype=np.float32), allow_pickle=False)
    return [(1, name, path)]


def test_known_face_high_confidence(tmp_path):
    result = provider().match(
        np.array([1.0, 0.0], dtype=np.float32), candidate(tmp_path, [1.0, 0.0])
    )
    assert result.display_name == "Mike"
    assert result.status == "KNOWN_HIGH_CONFIDENCE"


def test_possible_match_is_not_high_confidence(tmp_path):
    result = provider().match(
        np.array([1.0, 0.0], dtype=np.float32), candidate(tmp_path, [0.7, 0.7])
    )
    assert result.status == "POSSIBLE_MATCH"


def test_unknown_face_does_not_force_match(tmp_path):
    result = provider().match(
        np.array([1.0, 0.0], dtype=np.float32), candidate(tmp_path, [0.0, 1.0])
    )
    assert result is None


def test_no_enrolled_people():
    assert provider().match(np.array([1.0, 0.0], dtype=np.float32), []) is None


def test_disabled_provider_never_recognizes():
    disabled = DisabledFaceRecognitionProvider()
    assert disabled.embedding(np.zeros((100, 100, 3), dtype=np.uint8)) is None
    assert disabled.match(np.ones(2), []) is None
