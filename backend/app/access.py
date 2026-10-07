"""Lista CID-ów z dostępem (zakładka ADMIN) i ostatnie odmowy logowania.

Osobna baza na wolumenie - główna (polids.db) jest budowana z repo przy każdym obrazie."""

import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .config import settings

MAX_DENIED = 300


class StateBase(DeclarativeBase):
    pass


class AllowedUser(StateBase):
    __tablename__ = "allowed_users"

    cid: Mapped[str] = mapped_column(String(10), primary_key=True)
    note: Mapped[str | None] = mapped_column(String(120))
    name: Mapped[str | None] = mapped_column(String(80))  # z VATSIM, uzupełniane przy logowaniu
    added_by: Mapped[str | None] = mapped_column(String(10))
    added_at: Mapped[datetime] = mapped_column(DateTime)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class DeniedLogin(StateBase):
    __tablename__ = "denied_logins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cid: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str | None] = mapped_column(String(80))
    rating: Mapped[str | None] = mapped_column(String(5))
    at: Mapped[datetime] = mapped_column(DateTime)


_engine = None
_Session = None
_allowed: set[str] | None = None  # cache, jeden proces - unieważniany przy każdej zmianie
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


def _session():
    global _engine, _Session
    with _lock:
        if _Session is None:
            url = settings.state_database_url
            if url.startswith("sqlite:///"):
                Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
                                    pool_size=5, max_overflow=-1)
            StateBase.metadata.create_all(_engine)
            _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _Session()


def init_state():
    _session().close()
    allowed_cids()


def reset():
    """Do testów: pusta lista i nowe połączenie (np. po zmianie state_database_url)."""
    global _engine, _Session, _allowed
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = _Session = _allowed = None


def allowed_cids() -> set[str]:
    global _allowed
    if _allowed is None:
        with _session() as db:
            _allowed = set(db.scalars(select(AllowedUser.cid)))
    return _allowed


def is_allowed(cid: str) -> bool:
    return str(cid) in allowed_cids()


def _user_dict(u: AllowedUser) -> dict:
    return {"cid": u.cid, "note": u.note, "name": u.name, "added_by": u.added_by, "added_at": _iso(u.added_at),
            "last_login": _iso(u.last_login)}


def list_users() -> list[dict]:
    with _session() as db:
        return [_user_dict(u) for u in db.scalars(select(AllowedUser).order_by(AllowedUser.added_at.desc()))]


def add_user(cid: str, note: str | None, by: str | None) -> dict:
    global _allowed
    with _session() as db:
        if db.get(AllowedUser, cid):
            raise ValueError(cid)
        last = db.scalars(select(DeniedLogin).where(DeniedLogin.cid == cid).order_by(DeniedLogin.at.desc())).first()
        u = AllowedUser(cid=cid, note=note, name=last.name if last else None, added_by=by, added_at=_now())
        db.add(u)
        db.execute(delete(DeniedLogin).where(DeniedLogin.cid == cid))
        db.commit()
        _allowed = None
        return _user_dict(u)


def update_note(cid: str, note: str | None) -> dict | None:
    with _session() as db:
        u = db.get(AllowedUser, cid)
        if not u:
            return None
        u.note = note
        db.commit()
        return _user_dict(u)


def remove_user(cid: str) -> bool:
    global _allowed
    with _session() as db:
        n = db.execute(delete(AllowedUser).where(AllowedUser.cid == cid)).rowcount
        db.commit()
    _allowed = None
    return n > 0


def record_login(cid: str, name: str | None):
    with _session() as db:
        u = db.get(AllowedUser, cid)
        if u:
            u.last_login = _now()
            u.name = name or u.name
            db.commit()


def record_denied(cid: str, name: str | None, rating: str | None):
    with _session() as db:
        db.add(DeniedLogin(cid=cid, name=name, rating=rating, at=_now()))
        db.flush()
        old = db.scalars(select(DeniedLogin.id).order_by(DeniedLogin.id.desc()).offset(MAX_DENIED)).all()
        if old:
            db.execute(delete(DeniedLogin).where(DeniedLogin.id.in_(old)))
        db.commit()


def denied_attempts() -> list[dict]:
    """Odmowy pogrupowane po CID, najnowsze pierwsze."""
    out: dict[str, dict] = {}
    with _session() as db:
        for d in db.scalars(select(DeniedLogin).order_by(DeniedLogin.at.desc())):
            if d.cid in out:
                out[d.cid]["count"] += 1
            else:
                out[d.cid] = {"cid": d.cid, "name": d.name, "rating": d.rating, "last": _iso(d.at), "count": 1}
    return list(out.values())


def clear_denied():
    with _session() as db:
        db.execute(delete(DeniedLogin))
        db.commit()
