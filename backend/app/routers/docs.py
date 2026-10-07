from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document

router = APIRouter(prefix="/api/docs", tags=["docs"])


def _dict(d: Document):
    return {"id": d.id, "title": d.title, "category": d.category, "description": d.description,
            "url": f"/files/docs/{d.filename}"}


@router.get("")
def list_docs(db: Session = Depends(get_db)):
    """Dokumenty PDF z folderu data/docs/ (podfolder = kategoria). Folder skanowany przy starcie i przez /api/import."""
    return [_dict(d) for d in db.scalars(select(Document).order_by(Document.category, Document.title))]
