from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    jarvis_host: str = "127.0.0.1"
    jarvis_port: int = 8765
    jarvis_admin_token: str = Field("change-this-to-a-long-random-value", min_length=12)
    jarvis_admin_username: str = Field("admin", min_length=1, max_length=80)
    jarvis_admin_password: str = Field("change-this-password", min_length=8)
    admin_session_days: int = Field(30, ge=1, le=365)
    device_gateway_host: str = "127.0.0.1"
    device_gateway_port: int = 8766
    jarvis_core_url: str = "http://127.0.0.1:8765"
    mcp_allowed_hosts: str = "127.0.0.1,localhost"
    data_dir: Path = Path("./data")
    log_dir: Path = Path("./logs")
    camera_mode: str = "test"
    camera_name: str = "Tapo C101"
    camera_host: str = ""
    camera_username: str = ""
    camera_password: str = ""
    camera_rtsp_url_main: str = ""
    camera_rtsp_url_sub: str = ""
    vision_provider: str = "mock"
    vision_model: str = "yolo11n.pt"
    detection_confidence: float = Field(0.5, ge=0.1, le=1)
    detection_fps: float = Field(3, ge=0.2, le=30)
    presence_freshness_seconds: float = Field(3, ge=1, le=15)
    presence_hold_seconds: float = Field(2.5, ge=0, le=10)
    voice_satellite: str = "simulator"
    visitor_listen_timeout_seconds: float = Field(15, ge=3, le=120)
    visitor_conversation_max_seconds: float = Field(120, ge=15, le=600)
    visitor_conversation_max_turns: int = Field(8, ge=1, le=20)
    personalize_known_visitor_greeting: bool = False
    ai_provider: str = "ollama"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    dwell_seconds: float = Field(2.5, ge=0.2, le=30)
    disappear_grace_seconds: float = Field(4, ge=0, le=30)
    greeting_cooldown_seconds: float = Field(60, ge=0, le=3600)
    session_timeout_seconds: float = Field(300, ge=10, le=3600)
    zone_observation: str = "0.02,0.05;0.98,0.05;0.98,0.98;0.02,0.98"
    zone_approach: str = "0.15,0.25;0.85,0.25;0.90,0.98;0.10,0.98"
    zone_interaction: str = "0.28,0.48;0.72,0.48;0.82,0.98;0.18,0.98"
    store_transcripts: bool = True
    store_visitor_images: bool = True
    store_badge_images: bool = True
    record_audio: bool = False
    face_recognition: bool = False
    face_detection_model: Path = Path("./data/models/face_detection_yunet_2026may.onnx")
    face_recognition_model: Path = Path(
        "./data/models/face_recognition_sface_2021dec.onnx"
    )
    face_recognition_threshold: float = Field(0.45, ge=0.2, le=0.9)
    face_possible_threshold: float = Field(0.36, ge=0.1, le=0.8)
    media_retention_days: int = Field(30, ge=1, le=3650)
    unknown_visitor_media_retention_days: int = Field(7, ge=1, le=365)
    visitor_candidate_interval_seconds: float = Field(1.5, ge=0.5, le=10)
    notification_provider: str = "log"
    ha_mqtt_enabled: bool = False

    @field_validator("camera_mode")
    @classmethod
    def camera_mode_ok(cls, v):
        if v not in {"live", "test"}:
            raise ValueError("CAMERA_MODE must be live or test")
        return v

    @field_validator("voice_satellite")
    @classmethod
    def voice_satellite_ok(cls, v):
        if v not in {"simulator", "aipi_stock"}:
            raise ValueError("VOICE_SATELLITE must be simulator or aipi_stock")
        return v

    @field_validator(
        "data_dir", "log_dir", "face_detection_model", "face_recognition_model"
    )
    @classmethod
    def portable_path(cls, v):
        v = Path(v)
        return v if v.is_absolute() else ROOT / v

    def rtsp_url(self, main=False):
        explicit = self.camera_rtsp_url_main if main else self.camera_rtsp_url_sub
        if explicit:
            return explicit
        if not all((self.camera_host, self.camera_username, self.camera_password)):
            return ""
        from urllib.parse import quote

        return f"rtsp://{quote(self.camera_username, safe='')}:{quote(self.camera_password, safe='')}@{self.camera_host}:554/{'stream1' if main else 'stream2'}"

    def public(self):
        d = self.model_dump(mode="json")
        for k in (
            "camera_host",
            "camera_username",
            "camera_password",
            "jarvis_admin_token",
            "jarvis_admin_password",
        ):
            d[k] = "***" if d[k] else ""
        for k in ("camera_rtsp_url_main", "camera_rtsp_url_sub"):
            d[k] = "rtsp://***" if d[k] else ""
        return d


@lru_cache
def get_settings():
    return Settings()
