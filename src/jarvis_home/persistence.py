from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
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
    organization: Mapped[str | None] = mapped_column(String, nullable=True)
    relationship: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    face_data_path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String)
    last_seen: Mapped[str | None] = mapped_column(String, nullable=True)
    match_count: Mapped[int] = mapped_column(Integer, default=0)


class VisitorMedia(Base):
    __tablename__ = "visitor_media"
    __table_args__ = (UniqueConstraint("visitor_id", "media_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_id: Mapped[str] = mapped_column(ForeignKey("visitor_sessions.id"))
    media_type: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(String)
    captured_at: Mapped[str] = mapped_column(String)
    person_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    face_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, default=0)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    retained: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(String)


class FaceSample(Base):
    __tablename__ = "face_samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    known_person_id: Mapped[int] = mapped_column(ForeignKey("known_people.id"))
    source_visitor_id: Mapped[str | None] = mapped_column(String, nullable=True)
    image_path: Mapped[str] = mapped_column(String)
    embedding_path: Mapped[str] = mapped_column(String)
    quality_score: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


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
    last_successful_request: Mapped[str | None] = mapped_column(String, nullable=True)
    last_failed_request: Mapped[str | None] = mapped_column(String, nullable=True)
    connection_state: Mapped[str] = mapped_column(String, default="unknown")


class DeviceCredential(Base):
    __tablename__ = "device_credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    token_prefix: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String)
    revoked_at: Mapped[str | None] = mapped_column(String, nullable=True)


class DeviceToolPermission(Base):
    __tablename__ = "device_tool_permissions"
    __table_args__ = (UniqueConstraint("device_id", "tool_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    tool_name: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)


class DeviceAudit(Base):
    __tablename__ = "device_audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String)
    request: Mapped[str] = mapped_column(String)
    skill: Mapped[str] = mapped_column(String)
    result: Mapped[str] = mapped_column(Text)
    response_status: Mapped[str] = mapped_column(String)
    timestamp: Mapped[str] = mapped_column(String)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)


class FrontDoorEvent(Base):
    __tablename__ = "front_door_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String)
    camera_id: Mapped[str] = mapped_column(String, default="tapo-front-door")
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    known_person_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
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
        self._migrate_device_audit()
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
                "organization": "VARCHAR",
                "relationship": "VARCHAR",
                "notes": "TEXT",
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
            "last_successful_request": "VARCHAR",
            "last_failed_request": "VARCHAR",
            "connection_state": "VARCHAR DEFAULT 'unknown'",
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

    def _migrate_device_audit(self):
        additions = {
            "duration_ms": "FLOAT DEFAULT 0",
            "error_code": "VARCHAR",
        }
        with self.engine.begin() as connection:
            existing = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(device_audit)"
                ).fetchall()
            }
            for column, kind in additions.items():
                if column not in existing:
                    connection.exec_driver_sql(
                        f"ALTER TABLE device_audit ADD COLUMN {column} {kind}"
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
                    name="Front Door AiPi",
                    device_type="AIPI_LITE",
                    module="front_door",
                    provider="AIPI_LOCAL",
                    status="waiting_for_hardware",
                    workspace_id="home",
                    location="Front Door",
                    capabilities='["DISPLAY","BUTTON","WIFI","LOCAL_CONNECTION","STATUS"]',
                    created_at=utcnow(),
                    updated_at=utcnow(),
                ),
            ):
                if not s.get(Device, d.id):
                    s.add(d)
            s.flush()
            existing = {
                row.tool_name
                for row in s.scalars(
                    select(DeviceToolPermission).where(
                        DeviceToolPermission.device_id == "aipi-front-door"
                    )
                ).all()
            }
            for tool_name in (
                "jarvis.status",
                "jarvis.frontDoor.status",
                "jarvis.frontDoor.recent",
            ):
                if tool_name not in existing:
                    s.add(
                        DeviceToolPermission(
                            device_id="aipi-front-door",
                            tool_name=tool_name,
                            enabled=True,
                            created_at=utcnow(),
                            updated_at=utcnow(),
                        )
                    )
            s.commit()

    def event(self, event, detail=""):
        with self.Session() as s:
            s.add(SystemEvent(event=event, detail=detail, timestamp=utcnow()))
            s.commit()
