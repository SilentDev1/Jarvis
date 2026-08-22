from datetime import UTC, datetime

from sqlalchemy import Boolean, Float, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class VisitorSession(Base):
    __tablename__ = "visitor_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    arrival_time: Mapped[str] = mapped_column(String)
    departure_time: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    claimed_company: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    visitor_type: Mapped[str] = mapped_column(String, default="unknown")
    visitor_photo: Mapped[str | None] = mapped_column(String, nullable=True)
    badge_photo: Mapped[str | None] = mapped_column(String, nullable=True)
    badge_ocr: Mapped[str | None] = mapped_column(Text, nullable=True)
    package_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    conversation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    confidence: Mapped[float] = mapped_column(Float, default=0)
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("visitor_sessions.id"))
    role: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[str] = mapped_column(String)


class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    timestamp: Mapped[str] = mapped_column(String)


class Badge(Base):
    __tablename__ = "badges"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str] = mapped_column(String)
    image_path: Mapped[str] = mapped_column(String)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_candidate: Mapped[str | None] = mapped_column(String, nullable=True)
    company_candidate: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    timestamp: Mapped[str] = mapped_column(String)


class DetectionRecord(Base):
    __tablename__ = "detections"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    label: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[str] = mapped_column(String)


class PackageEvent(Base):
    __tablename__ = "package_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[str] = mapped_column(String)


class KnownPerson(Base):
    __tablename__ = "known_people"
    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    face_data_path: Mapped[str | None] = mapped_column(String, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)
    timestamp: Mapped[str] = mapped_column(String)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    device_type: Mapped[str] = mapped_column(String)
    module: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    last_seen: Mapped[str | None] = mapped_column(String, nullable=True)


class SystemEvent(Base):
    __tablename__ = "system_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event: Mapped[str] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[str] = mapped_column(String)


def utcnow():
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
        self.Session = sessionmaker(self.engine)

    def init(self):
        Base.metadata.create_all(self.engine)
        self._migrate_badge_evidence()
        self.seed_devices()

    def _migrate_badge_evidence(self):
        """Small idempotent migration for installations created before live OCR."""
        with self.engine.begin() as connection:
            existing = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(badges)"
                ).fetchall()
            }
            for column in ("name_candidate", "company_candidate"):
                if column not in existing:
                    connection.exec_driver_sql(
                        f"ALTER TABLE badges ADD COLUMN {column} VARCHAR"
                    )

    def seed_devices(self):
        with self.Session() as s:
            for d in (
                Device(
                    id="tapo-front-door",
                    name="Tapo C101",
                    device_type="camera",
                    module="front_door",
                    provider="tapo",
                    status="configured",
                ),
                Device(
                    id="aipi-front-door",
                    name="AiPi",
                    device_type="voice_satellite",
                    module="front_door",
                    provider="aipi",
                    status="waiting_for_hardware",
                ),
            ):
                if not s.get(Device, d.id):
                    s.add(d)
            s.commit()

    def event(self, event, detail=""):
        with self.Session() as s:
            s.add(SystemEvent(event=event, detail=detail, timestamp=utcnow()))
            s.commit()
