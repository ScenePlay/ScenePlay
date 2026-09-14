"""Shared pieces of the Grid.js server protocol:
GET  /api/<table>?search=&sort=+col,-col&start=&length=  -> {data, total}
POST /api/<table> {primeKey, field: value}                -> 204"""
from fastapi import Request, Response

from core.db import db
from security.deps import ApiError


def sort_clause(tbl, sort, columns, prime_key, extra=None):
    """Grid.js sort param -> ORDER BY columns (unknown names fall back to the pk)."""
    order = []
    if sort:
        for s in sort.split(','):
            if not s:
                continue
            direction, name = s[0], s[1:]
            if extra and name in extra:
                col = extra[name]
            else:
                if name not in columns:
                    name = prime_key
                col = getattr(tbl, name, None)
                if col is None:            # e.g. 'song_ID' vs the mapped song_id
                    col = tbl.__mapper__.primary_key[0]
            if direction == '-':
                col = col.desc()
            order.append(col)
    return order


def paginate(query, start, length):
    if start != -1 and length != -1:
        query = query.offset(start).limit(length)
    return query


def apply_update(tbl, columns, prime_key, data, skip=(), on_field=None):
    if not isinstance(data, dict) or prime_key not in data:
        raise ApiError(400, f'{prime_key} required')
    row = db.session.get(tbl, data[prime_key])
    if row is None:
        raise ApiError(404, 'row not found')
    for field in columns:
        if field in skip or field not in data:
            continue
        setattr(row, field, data[field])
        if on_field:
            on_field(field, data)
    db.session.commit()
    return Response(status_code=204)


def require_pk(data, prime_key):
    if not isinstance(data, dict) or prime_key not in data:
        raise ApiError(400, f'{prime_key} required')
    return data[prime_key]
