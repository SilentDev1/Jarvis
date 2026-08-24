from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from ..persistence import FrontDoorEvent, VisitorSession


class CoreSkill:
    def __init__(self, core_url: str, transport=None):
        self.core_url = core_url.rstrip("/")
        self.transport = transport

    def client(self):
        return httpx.AsyncClient(timeout=5, transport=self.transport)


class JarvisStatusSkill(CoreSkill):
    async def invoke(self) -> dict:
        try:
            async with self.client() as client:
                response = await client.get(f"{self.core_url}/health")
                response.raise_for_status()
                health = response.json()
        except (httpx.HTTPError, ValueError):
            return {
                "ok": False,
                "speech": "Jarvis Core is temporarily unavailable.",
                "status": "provider_failure",
            }
        online = health.get("status") == "ready"
        return {
            "ok": online,
            "speech": "Jarvis is online." if online else "Jarvis is not ready.",
            "status": "online" if online else "not_ready",
        }


class FrontDoorStatusSkill(CoreSkill):
    def __init__(self, core_url: str, store, transport=None):
        super().__init__(core_url, transport)
        self.store = store

    async def invoke(self) -> dict:
        try:
            async with self.client() as client:
                response = await client.get(f"{self.core_url}/api/front-door")
                response.raise_for_status()
                state = response.json()
        except (httpx.HTTPError, ValueError):
            return {
                "ok": False,
                "speech": "The front-door service is temporarily unavailable.",
                "status": "jarvis_offline",
            }
        camera_online = bool(state.get("camera", {}).get("connected"))
        tracks = state.get("vision", {}).get("tracks") or []
        person_count = len(tracks)
        person_present = person_count > 0
        session_id = state.get("session_id")
        visit = None
        with self.store.Session() as session:
            if session_id:
                visit = session.get(VisitorSession, session_id)
                if visit:
                    session.expunge(visit)

        identity_status = "NO_PERSON"
        known_person = None
        face_confidence = None
        if person_present:
            identity_status = "UNKNOWN"
            if visit and visit.face_match_status == "KNOWN_HIGH_CONFIDENCE":
                identity_status = "KNOWN"
                known_person = visit.recognized_name
                face_confidence = visit.recognition_confidence
            elif visit and visit.face_match_status == "POSSIBLE_MATCH":
                identity_status = "UNCERTAIN"

        if not camera_online:
            speech = "The front-door camera is offline."
            status = "camera_offline"
        elif not person_present:
            speech = "Nobody is currently at the front door."
            status = "clear"
        elif identity_status == "KNOWN" and known_person:
            speech = f"{known_person} is at the front door."
            status = "person_present"
        elif identity_status == "UNCERTAIN":
            speech = "There is someone at the front door, but I cannot identify them confidently."
            status = "person_present"
        elif person_count == 1:
            speech = "There is one person at the front door. I do not recognize them."
            status = "person_present"
        else:
            speech = f"There are {person_count} people at the front door. I do not recognize them."
            status = "person_present"

        return {
            "ok": camera_online,
            "status": status,
            "speech": speech,
            "cameraOnline": camera_online,
            "personPresent": person_present,
            "personCount": person_count,
            "identityStatus": identity_status,
            "knownPerson": known_person,
            "faceConfidence": face_confidence,
            "packagePresent": None,
            "packageDetectionAvailable": False,
            "lastDetectionTime": state.get("vision", {}).get("last_detection"),
            "visitorType": visit.visitor_type if visit else None,
            "companyClaimed": visit.claimed_company if visit else None,
            "uniformDetected": None,
            "badgeDetected": bool(visit and visit.badge_photo),
            "evidenceNotice": "Identity and company context are evidence hints, not authentication.",
        }


class FrontDoorRecentSkill:
    def __init__(self, store, max_events=5, window_hours=24):
        self.store = store
        self.max_events = max_events
        self.window_hours = window_hours

    async def invoke(self) -> dict:
        cutoff = datetime.now(UTC) - timedelta(hours=self.window_hours)
        with self.store.Session() as session:
            records = session.scalars(
                select(FrontDoorEvent)
                .where(FrontDoorEvent.timestamp >= cutoff.isoformat())
                .order_by(FrontDoorEvent.timestamp.desc())
                .limit(self.max_events)
            ).all()
            events = [
                {
                    "type": record.event_type,
                    "timestamp": record.timestamp,
                    "confidence": record.confidence,
                }
                for record in records
            ]
            if not events:
                visits = session.scalars(
                    select(VisitorSession)
                    .where(VisitorSession.arrival_time >= cutoff.isoformat())
                    .order_by(VisitorSession.arrival_time.desc())
                    .limit(self.max_events)
                ).all()
                events = [
                    {
                        "type": "KNOWN_PERSON"
                        if visit.face_match_status == "KNOWN_HIGH_CONFIDENCE"
                        else "VISITOR_SESSION",
                        "timestamp": visit.arrival_time,
                        "identityStatus": visit.face_match_status,
                        "knownPerson": visit.recognized_name,
                        "visitorType": visit.visitor_type,
                    }
                    for visit in visits
                ]
        if not events:
            speech = (
                "There has been no recorded front-door activity in the last 24 hours."
            )
        else:
            latest = events[0]
            if latest.get("knownPerson"):
                speech = (
                    f"The most recent recorded visitor was {latest['knownPerson']}."
                )
            elif latest["type"] in {
                "PERSON_DETECTED",
                "UNKNOWN_PERSON",
                "VISITOR_SESSION",
            }:
                speech = "The most recent activity was an unidentified person at the front door."
            elif latest["type"] == "PACKAGE_DETECTED":
                speech = (
                    "The most recent activity was a package detected at the front door."
                )
            else:
                speech = "Recent front-door activity is available in the event summary."
        return {
            "ok": True,
            "status": "available",
            "speech": speech,
            "windowHours": self.window_hours,
            "events": events,
            "bounded": True,
        }
