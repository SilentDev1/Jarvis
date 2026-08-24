from pathlib import Path

from sqlalchemy import select

from ...persistence import FaceSample, KnownPerson, VisitorMedia, VisitorSession, utcnow


class EnrollmentError(ValueError):
    pass


class AmbiguousEnrollmentError(EnrollmentError):
    pass


class KnownPersonService:
    def __init__(self, store, data_dir: Path, recognition, visitor_media):
        self.store = store
        self.data_dir = data_dir
        self.recognition = recognition
        self.visitor_media = visitor_media

    def enroll(
        self,
        visitor_id: str,
        display_name: str,
        organization: str | None = None,
        relationship: str | None = None,
        notes: str | None = None,
        category: str | None = None,
    ) -> dict:
        candidate = self.visitor_media.candidate(visitor_id)
        if not candidate or not candidate["face_available"]:
            raise EnrollmentError("No clear face was captured for this visit")
        if candidate["ambiguous"]:
            raise AmbiguousEnrollmentError("Enrollment candidate is ambiguous")
        with self.store.Session() as session:
            face_media = session.scalar(
                select(VisitorMedia).where(
                    VisitorMedia.visitor_id == visitor_id,
                    VisitorMedia.media_type == "FACE_CROP",
                )
            )
            photo = self.visitor_media.resolve(face_media.path if face_media else None)
        if photo is None or not photo.is_file():
            raise EnrollmentError("Enrollment face image is unavailable")
        import cv2

        image = cv2.imread(str(photo))
        embedding = self.recognition.embedding(image) if image is not None else None
        if embedding is None:
            raise EnrollmentError("No clear face was captured for this visit")
        with self.store.Session() as session:
            person = KnownPerson(
                display_name=display_name,
                category=category,
                organization=organization,
                relationship=relationship,
                notes=notes,
                enabled=True,
                source_session_id=visitor_id,
                created_at=utcnow(),
                match_count=0,
            )
            session.add(person)
            session.flush()
            relative = Path("faces") / f"person_{person.id}" / "sample_1.npy"
            self.recognition.save_embedding(embedding, self.data_dir / relative)
            person.face_data_path = str(relative)
            session.add(
                FaceSample(
                    known_person_id=person.id,
                    source_visitor_id=visitor_id,
                    image_path=face_media.path,
                    embedding_path=str(relative),
                    quality_score=face_media.quality_score,
                    created_at=utcnow(),
                    enabled=True,
                )
            )
            visit = session.get(VisitorSession, visitor_id)
            if visit:
                visit.known_person_id = person.id
                visit.recognized_name = display_name
                visit.recognition_confidence = 1.0
                visit.face_match_status = "KNOWN_HIGH_CONFIDENCE"
            session.commit()
            person_id = person.id
        self.visitor_media.mark_retained(visitor_id)
        return {"id": person_id, "display_name": display_name, "visitor_id": visitor_id}
