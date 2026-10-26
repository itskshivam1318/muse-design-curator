import hashlib

from sqlalchemy.orm import Session

from app.db.ids import now_iso
from app.db.models import ExtensionToken


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def add(session: Session, token: str) -> ExtensionToken:
    row = ExtensionToken(token_hash=hash_token(token))
    session.add(row)
    session.flush()
    return row


def verify(session: Session, token: str) -> bool:
    row = session.get(ExtensionToken, hash_token(token))
    if row is None:
        return False
    row.last_used_at = now_iso()
    session.flush()
    return True
