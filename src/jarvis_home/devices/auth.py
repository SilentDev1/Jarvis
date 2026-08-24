import hashlib
import secrets

from sqlalchemy import select

from ..persistence import Device, DeviceCredential, utcnow


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_device_token(store, device_id: str) -> str:
    token = "jdv_" + secrets.token_urlsafe(32)
    with store.Session() as session:
        device = session.get(Device, device_id)
        if device is None:
            raise ValueError("Unknown device")
        session.add(
            DeviceCredential(
                device_id=device_id,
                token_hash=token_hash(token),
                token_prefix=token[:12],
                enabled=True,
                created_at=utcnow(),
            )
        )
        session.commit()
    return token


def authenticate_device(store, token: str | None) -> Device | None:
    if not token:
        return None
    digest = token_hash(token)
    with store.Session() as session:
        candidate = session.scalar(
            select(DeviceCredential).where(
                DeviceCredential.enabled.is_(True),
                DeviceCredential.token_hash == digest,
            )
        )
        if candidate and secrets.compare_digest(candidate.token_hash, digest):
            device = session.get(Device, candidate.device_id)
            if device and device.enabled:
                session.expunge(device)
                return device
    return None


def revoke_device_tokens(store, device_id: str) -> int:
    count = 0
    with store.Session() as session:
        credentials = session.scalars(
            select(DeviceCredential).where(
                DeviceCredential.device_id == device_id,
                DeviceCredential.enabled.is_(True),
            )
        ).all()
        for credential in credentials:
            credential.enabled = False
            credential.revoked_at = utcnow()
            count += 1
        session.commit()
    return count
