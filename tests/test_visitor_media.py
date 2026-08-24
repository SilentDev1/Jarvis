from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import select

from jarvis_home.modules.front_door.known_people import (
    AmbiguousEnrollmentError,
    EnrollmentError,
    KnownPersonService,
)
from jarvis_home.modules.front_door.recognition import FaceCandidate
from jarvis_home.modules.front_door.visitor_media import VisitorMediaService
from jarvis_home.persistence import (
    FaceSample,
    KnownPerson,
    Store,
    VisitorMedia,
    VisitorSession,
    utcnow,
)


class FakeRecognition:
    def __init__(self, qualities=None, face=True, ambiguous=False):
        self.qualities = list(qualities or [50])
        self.face = face
        self.ambiguous = ambiguous

    def candidate(self, image):
        if not self.face:
            return None
        quality = (
            self.qualities.pop(0) if len(self.qualities) > 1 else self.qualities[0]
        )
        return FaceCandidate(
            image[2:18, 2:18], 0.9, quality, 2 if self.ambiguous else 1, self.ambiguous
        )

    def embedding(self, _image):
        return np.array([1.0, 0.0], dtype=np.float32) if self.face else None

    def save_embedding(self, embedding, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        np.save(path, embedding, allow_pickle=False)


def setup_media(tmp_path, recognition=None, visitor_ids=("visit-1",)):
    store = Store(tmp_path / "jarvis.db")
    store.init()
    with store.Session() as session:
        for visitor_id in visitor_ids:
            session.add(
                VisitorSession(
                    id=visitor_id,
                    arrival_time=utcnow(),
                    status="active",
                    visitor_type="unknown",
                    confidence=0,
                )
            )
        session.commit()
    return store, VisitorMediaService(store, tmp_path, recognition)


def image(value=100):
    pixels = np.full((24, 24, 3), value, dtype=np.uint8)
    pixels[::2, ::2] = 255 - value
    return pixels


def test_snapshot_face_crop_best_frame_and_restart(tmp_path):
    store, service = setup_media(tmp_path, FakeRecognition([20, 80, 10]))
    first = service.capture_candidate("visit-1", image(40), 0.6)
    assert set(first["updated"]) == {"SNAPSHOT", "FACE_CROP"}
    service.capture_candidate("visit-1", image(80), 0.9)
    service.capture_candidate("visit-1", image(20), 0.2)
    with store.Session() as session:
        face = session.scalar(
            select(VisitorMedia).where(VisitorMedia.media_type == "FACE_CROP")
        )
        assert face.quality_score == 80
        assert face.visitor_id == "visit-1"
    restarted = VisitorMediaService(store, tmp_path, FakeRecognition())
    assert restarted.candidate("visit-1")["face_available"] is True


def test_no_face_blocks_enrollment_without_breaking_snapshot(tmp_path):
    recognition = FakeRecognition(face=False)
    store, media = setup_media(tmp_path, recognition)
    media.capture_candidate("visit-1", image(), 0.8)
    assert media.candidate("visit-1")["snapshot_available"] is True
    assert media.candidate("visit-1")["face_available"] is False
    service = KnownPersonService(store, tmp_path, recognition, media)
    try:
        service.enroll("visit-1", "Nobody")
    except EnrollmentError:
        pass
    else:
        raise AssertionError("Enrollment without a face must fail")


def test_enrollment_creates_sample_and_updates_active_visitor(tmp_path):
    recognition = FakeRecognition()
    store, media = setup_media(tmp_path, recognition)
    media.capture_candidate("visit-1", image(), 0.9)
    result = KnownPersonService(store, tmp_path, recognition, media).enroll(
        "visit-1", "Morgan", "Example Co", "Neighbor", "Approved locally"
    )
    with store.Session() as session:
        person = session.get(KnownPerson, result["id"])
        visit = session.get(VisitorSession, "visit-1")
        samples = session.scalars(
            select(FaceSample).where(FaceSample.known_person_id == person.id)
        ).all()
        assert person.organization == "Example Co"
        assert visit.recognized_name == "Morgan"
        assert visit.face_match_status == "KNOWN_HIGH_CONFIDENCE"
        assert len(samples) == 1
        assert (tmp_path / samples[0].embedding_path).is_file()


def test_ambiguous_multi_person_candidate_is_not_enrolled(tmp_path):
    recognition = FakeRecognition(ambiguous=True)
    store, media = setup_media(tmp_path, recognition)
    media.capture_candidate("visit-1", image(), 0.9, person_count=2)
    service = KnownPersonService(store, tmp_path, recognition, media)
    try:
        service.enroll("visit-1", "Wrong Person")
    except AmbiguousEnrollmentError:
        pass
    else:
        raise AssertionError("Ambiguous enrollment must fail")


def test_clear_single_person_candidate_replaces_ambiguous_candidate(tmp_path):
    recognition = FakeRecognition([90, 50], ambiguous=True)
    _store, media = setup_media(tmp_path, recognition)
    media.capture_candidate("visit-1", image(), 0.9, person_count=2)
    recognition.ambiguous = False
    media.capture_candidate("visit-1", image(60), 0.7, person_count=1)
    assert media.candidate("visit-1")["ambiguous"] is False


def test_visitors_are_isolated_and_media_is_not_duplicated(tmp_path):
    store, media = setup_media(tmp_path, FakeRecognition(), ("visit-1", "visit-2"))
    for _index in range(4):
        media.capture_candidate("visit-1", image(), 0.8)
    media.capture_candidate("visit-2", image(60), 0.7)
    with store.Session() as session:
        rows = session.scalars(select(VisitorMedia)).all()
        assert len([row for row in rows if row.visitor_id == "visit-1"]) == 2
        assert len([row for row in rows if row.visitor_id == "visit-2"]) == 2


def test_cleanup_expires_unknown_but_preserves_active_and_enrolled(tmp_path):
    recognition = FakeRecognition()
    store, media = setup_media(tmp_path, recognition, ("old", "active", "known"))
    old_time = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    for visitor_id in ("old", "active", "known"):
        media.capture_candidate(visitor_id, image(), 0.8, captured_at=old_time)
    with store.Session() as session:
        session.get(VisitorSession, "old").status = "complete"
        session.get(VisitorSession, "known").status = "complete"
        session.commit()
    KnownPersonService(store, tmp_path, recognition, media).enroll("known", "Known")
    result = media.cleanup(7)
    assert result["rows"] == 2
    assert media.candidate("active")["snapshot_available"] is True
    assert media.candidate("known")["face_available"] is True
    assert media.candidate("old")["face_available"] is False


def test_path_traversal_is_rejected(tmp_path):
    _store, media = setup_media(tmp_path, FakeRecognition())
    assert media.resolve("../../etc/passwd") is None
