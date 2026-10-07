from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Callsign

router = APIRouter(prefix="/api/callsigns", tags=["callsign"])


@router.get("")
def search(q: str = "", prefix: str = "", category: str = "", limit: int = Query(200, ge=1, le=2000),
           db: Session = Depends(get_db)):
    stmt = select(Callsign)
    if category:
        stmt = stmt.where(Callsign.category == category.upper())
    if prefix:
        stmt = stmt.where(Callsign.icao.startswith(prefix.upper()))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Callsign.icao.ilike(like), Callsign.name.ilike(like),
                              Callsign.telephony.ilike(like), Callsign.country.ilike(like)))
        # dokładne trafienie w kod ICAO na górze listy
        stmt = stmt.order_by(case((Callsign.icao == q.upper(), 0), else_=1), Callsign.icao)
    else:
        stmt = stmt.order_by(Callsign.icao)
    return [{"icao": c.icao, "name": c.name, "telephony": c.telephony, "country": c.country, "category": c.category}
            for c in db.scalars(stmt.limit(min(limit, 2000)))]
