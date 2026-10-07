from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, Field

from .. import access
from ..auth import current_user, require_admin
from ..config import csv_set, settings

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

CID = r"^\d{6,8}$"


class UserIn(BaseModel):
    cid: str = Field(pattern=CID)
    note: str = Field("", max_length=120)


class NoteIn(BaseModel):
    note: str = Field("", max_length=120)


@router.get("/users")
def users():
    """Lista CID-ów z dostępem + administratorzy z konfiguracji (POLIDS_AUTH_ADMIN_CIDS)."""
    return {"admins": sorted(csv_set(settings.auth_admin_cids)), "users": access.list_users()}


@router.post("/users", status_code=201)
def add_user(body: UserIn, request: Request):
    me = current_user(request)
    try:
        return access.add_user(body.cid, body.note.strip() or None, by=me["cid"] if me else None)
    except ValueError:
        raise HTTPException(409, f"CID {body.cid} jest już na liście") from None


@router.patch("/users/{cid}")
def edit_user(body: NoteIn, cid: str = Path(pattern=CID)):
    u = access.update_note(cid, body.note.strip() or None)
    if not u:
        raise HTTPException(404, f"Nie ma CID {cid} na liście")
    return u


@router.delete("/users/{cid}", status_code=204)
def remove_user(cid: str = Path(pattern=CID)):
    if not access.remove_user(cid):
        raise HTTPException(404, f"Nie ma CID {cid} na liście")
    return Response(status_code=204)


@router.get("/denied")
def denied():
    """Ostatnie odmowy logowania (po CID)."""
    return access.denied_attempts()


@router.delete("/denied", status_code=204)
def clear_denied():
    access.clear_denied()
    return Response(status_code=204)
