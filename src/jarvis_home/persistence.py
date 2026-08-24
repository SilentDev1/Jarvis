from datetime import UTC, datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, create_engine
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
    known_person_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recognized_name: Mapped[str | None] = mapped_column(String, nullable=True)
    recognition_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_match_status: Mapped[str] = mapped_column(String, default="UNKNOWN")


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
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    face_data_path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)
    last_seen: Mapped[str | None] = mapped_column(String, nullable=True)
    match_count: Mapped[int] = mapped_column(Integer, default=0)


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
    workspace_id: Mapped[str] = mapped_column(String, default="home")
    device_identifier: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    capabilities: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)


class DeviceCredential(Base):
    __tablename__ = "device_credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    token_prefix: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String)
    revoked_at: Mapped[str | None] = mapped_column(String, nullable=True)


class DeviceAudit(Base):
    __tablename__ = "device_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String)
    request: Mapped[str] = mapped_column(String)
    skill: Mapped[str] = mapped_column(String)
    result: Mapped[str] = mapped_column(Text)
    response_status: Mapped[str] = mapped_column(String)
    timestamp: Mapped[str] = mapped_column(String)


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
        self._migrate_face_recognition()
        self._migrate_devices()
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

    def _migrate_face_recognition(self):
        """Idempotently upgrade databases created before local face matching."""
        additions = {
            "visitor_sessions": {
                "known_person_id": "INTEGER",
                "recognized_name": "VARCHAR",
                "recognition_confidence": "FLOAT",
                "face_match_status": "VARCHAR DEFAULT 'UNKNOWN'",
            },
            "known_people": {
                "source_session_id": "VARCHAR",
                "category": "VARCHAR",
                "created_at": "VARCHAR",
                "last_seen": "VARCHAR",
                "match_count": "INTEGER DEFAULT 0",
            },
        }
        with self.engine.begin() as connection:
            for table, columns in additions.items():
                existing = {
                    row[1]
                    for row in connection.exec_driver_sql(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                }
                for column, kind in columns.items():
                    if column not in existing:
                        connection.exec_driver_sql(
                            f"ALTER TABLE {table} ADD COLUMN {column} {kind}"
                        )
            connection.exec_driver_sql(
                "UPDATE known_people SET created_at = COALESCE(created_at, ?) ",
                (utcnow(),),
            )

    def _migrate_devices(self):
        additions = {
            "workspace_id": "VARCHAR DEFAULT 'home'",
            "device_identifier": "VARCHAR",
            "enabled": "BOOLEAN DEFAULT 1",
            "location": "VARCHAR",
            "capabilities": "TEXT DEFAULT '[]'",
            "created_at": "VARCHAR",
            "updated_at": "VARCHAR",
        }
        now = utcnow()
        with self.engine.begin() as connection:
            existing = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(devices)"
                ).fetchall()
            }
            for column, kind in additions.items():
                if column not in existing:
                    connection.exec_driver_sql(
                        f"ALTER TABLE devices ADD COLUMN {column} {kind}"
                    )
            connection.exec_driver_sql(
                "UPDATE devices SET created_at=COALESCE(created_at, ?), "
                "updated_at=COALESCE(updated_at, ?)",
                (now, now),
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
                    workspace_id="home",
                    location="Front Door",
                    capabilities='["VIDEO"]',
                    created_at=utcnow(),
                    updated_at=utcnow(),
                ),
                Device(
                    id="aipi-front-door",
                    name="AiPi",
                    device_type="voice_satellite",
                    module="front_door",
                    provider="aipi",
                    status="waiting_for_hardware",
                    workspace_id="home",
                    location="Front Door",
                    capabilities='["VOICE_INPUT","VOICE_OUTPUT","DISPLAY","BUTTON"]',
                    created_at=utcnow(),
                    updated_at=utcnow(),
                ),
            ):
                if not s.get(Device, d.id):
                    s.add(d)
            s.commit()

    def event(self, event, detail=""):
        with self.Session() as s:
            s.add(SystemEvent(event=event, detail=detail, timestamp=utcnow()))
            s.commit()
