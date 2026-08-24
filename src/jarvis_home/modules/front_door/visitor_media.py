from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from ...persistence import FaceSample, VisitorMedia, VisitorSession, utcnow
from .media import save_jpeg, sharpness


class VisitorMediaService:
    """Owns bounded local visitor media selection, access, and retention."""

    def __init__(self, store, data_dir: Path, recognition=None):
        self.store = store
        self.data_dir = data_dir.resolve()
        self.recognition = recognition

    def _relative(self, visitor_id: str, name: str) -> Path:
        return Path("media") / "visitors" / visitor_id / name

    def resolve(self, relative: str | None) -> Path | None:
        if not relative:
            return None
        candidate = (self.data_dir / relative).resolve()
        return candidate if candidate.is_relative_to(self.data_dir) else None

    def capture_candidate(
        self,
        visitor_id: str,
        image,
        person_confidence: float | None = None,
        person_count: int = 1,
        captured_at: str | None = None,
    ) -> dict:
        captured_at = captured_at or utcnow()
        face = self.recognition.candidate(image) if self.recognition else None
        ambiguous = person_count > 1 or bool(face and face.ambiguous)
        snapshot_quality = (
            min(100.0, sharpness(image) / 4) + (person_confidence or 0) * 10
        )
        candidates = [
            (
                "SNAPSHOT",
                self._relative(visitor_id, "snapshot.jpg"),
                image,
                snapshot_quality,
                None,
            )
        ]
        if face is not None:
            candidates.append(
                (
                    "FACE_CROP",
                    self._relative(visitor_id, "face.jpg"),
                    face.crop,
                    face.quality_score,
                    face.confidence,
                )
            )
        updated = []
        with self.store.Session() as session:
            visit = session.get(VisitorSession, visitor_id)
            if visit is None:
                raise ValueError("Unknown visitor")
            for media_type, relative, pixels, quality, face_confidence in candidates:
                record = session.scalar(
                    select(VisitorMedia).where(
                        VisitorMedia.visitor_id == visitor_id,
                        VisitorMedia.media_type == media_type,
                    )
                )
                if record is not None:
                    if not record.ambiguous and ambiguous:
                        continue
                    if (
                        record.ambiguous == ambiguous
                        and record.quality_score >= quality
                    ):
                        continue
                save_jpeg(pixels, self.data_dir / relative)
                if record is None:
                    record = VisitorMedia(
                        visitor_id=visitor_id,
                        media_type=media_type,
                        path=str(relative),
                        captured_at=captured_at,
                        created_at=utcnow(),
                    )
                    session.add(record)
                record.path = str(relative)
                record.captured_at = captured_at
                record.person_confidence = person_confidence
                record.face_confidence = face_confidence
                record.quality_score = round(quality, 2)
                record.ambiguous = ambiguous
                if media_type == "SNAPSHOT":
                    visit.visitor_photo = str(relative)
                updated.append(media_type)
            session.commit()
        return {
            "updated": updated,
            "face_detected": face is not None,
            "ambiguous": ambiguous,
            "face_quality": face.quality_score if face else None,
        }

    def candidate(self, visitor_id: str) -> dict | None:
        with self.store.Session() as session:
            visit = session.get(VisitorSession, visitor_id)
            if visit is None:
                return None
            records = {
                row.media_type: row
                for row in session.scalars(
                    select(VisitorMedia).where(VisitorMedia.visitor_id == visitor_id)
                ).all()
            }
            face = records.get("FACE_CROP")
            snapshot = records.get("SNAPSHOT")
            snapshot_path = self.resolve(snapshot.path if snapshot else None)
            face_path = self.resolve(face.path if face else None)
            return {
                "visitor_id": visitor_id,
                "status": visit.status,
                "snapshot_available": bool(snapshot_path and snapshot_path.is_file()),
                "face_available": bool(face_path and face_path.is_file()),
                "face_quality": face.quality_score if face else None,
                "ambiguous": bool(face and face.ambiguous),
            }

    def mark_retained(self, visitor_id: str) -> None:
        with self.store.Session() as session:
            for row in session.scalars(
                select(VisitorMedia).where(VisitorMedia.visitor_id == visitor_id)
            ).all():
                row.retained = True
            session.commit()

    def cleanup(self, retention_days: int, limit: int = 200) -> dict:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        removed_rows = 0
        removed_files = 0
        with self.store.Session() as session:
            protected = {
                row.image_path for row in session.scalars(select(FaceSample)).all()
            }
            rows = session.scalars(
                select(VisitorMedia)
                .join(VisitorSession, VisitorSession.id == VisitorMedia.visitor_id)
                .where(
                    VisitorSession.status != "active",
                    VisitorSession.known_person_id.is_(None),
                    VisitorMedia.retained.is_(False),
                    VisitorMedia.captured_at < cutoff.isoformat(),
                )
                .limit(limit)
            ).all()
            for row in rows:
                if row.path in protected:
                    continue
                path = self.resolve(row.path)
                if path and path.is_file():
                    path.unlink()
                    removed_files += 1
                session.delete(row)
                removed_rows += 1
            session.commit()
        return {"rows": removed_rows, "files": removed_files}
