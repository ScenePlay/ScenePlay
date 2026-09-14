"""Download-status lexicon feed (routes/dnLoadStatus_table.py)."""
from fastapi import APIRouter

from models.status import lutstatus as tbl

router = APIRouter()


@router.get('/api/dnLoadStatus')
def data():
    return {'data': [r.to_dict() for r in tbl.query.order_by(tbl.status_ID)]}
