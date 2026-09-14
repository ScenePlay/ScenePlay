"""Genre lookup feed (routes/genre_table.py — its page template never existed)."""
from fastapi import APIRouter

from models.genre import lutgenre as tbl

router = APIRouter()


@router.get('/api/genre')
def data():
    return {'data': [r.to_dict() for r in tbl.query.order_by(tbl.genre)]}
