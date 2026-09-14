"""DM-only account management (ported from routes/auth.py register/edit/
delete/reset-password)."""
from datetime import datetime

from fastapi import APIRouter, Depends

from core.db import db
from models.user import tblUsers
from schemas.auth import UserCreate, UserEdit, UserResetPassword
from security.deps import ApiError, require_dm

router = APIRouter(prefix='/api/v1/users', dependencies=[Depends(require_dm)])


def _user_row(u):
    d = u.to_dict()
    d['characters'] = [{'character_id': c.character_id, 'name': c.name}
                       for c in getattr(u, 'characters', [])]
    return d


@router.get('')
def list_users():
    return {'users': [_user_row(u) for u in tblUsers.query.order_by(tblUsers.display_name).all()]}


@router.post('')
def create_user(req: UserCreate):
    username = req.username.strip()
    if tblUsers.query.filter_by(username=username).first():
        raise ApiError(400, f'Username "{username}" is already taken.')
    user = tblUsers(username=username, display_name=req.display_name.strip(),
                    role=req.role if req.role in ('dm', 'player') else 'player', active=1,
                    created_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    user.set_password(req.password)
    db.session.add(user)
    db.session.commit()
    return {'ok': True, 'message': f'Account created for {user.display_name}.', 'user': user.to_dict()}


@router.post('/{user_id}/edit')
def edit_user(user_id: int, req: UserEdit, me=Depends(require_dm)):
    user = tblUsers.query.get_or_404(user_id)
    username = req.username.strip()
    display_name = req.display_name.strip()
    clash = tblUsers.query.filter(tblUsers.username == username,
                                  tblUsers.user_id != user_id).first()
    if clash:
        raise ApiError(400, f'Username "{username}" is already taken.')
    old_login = user.username
    user.username = username
    user.display_name = display_name
    db.session.commit()
    if old_login != username:
        msg = f'{display_name} updated — they log in as "{username}" from now on.'
    else:
        msg = f'{display_name} updated.'
    return {'ok': True, 'message': msg, 'user': user.to_dict()}


@router.post('/{user_id}/reset-password')
def reset_password(user_id: int, req: UserResetPassword):
    user = tblUsers.query.get_or_404(user_id)
    user.set_password(req.new_password.strip())
    db.session.commit()
    return {'ok': True, 'message': f'Password reset for {user.display_name}.'}


@router.post('/{user_id}/delete')
def delete_user(user_id: int, me=Depends(require_dm)):
    user = tblUsers.query.get_or_404(user_id)
    # never yourself: guarantees at least one DM survives
    if user.user_id == me.user_id:
        raise ApiError(400, 'You cannot delete your own account while logged in to it.')
    moved = 0
    for char in list(getattr(user, 'characters', [])):
        char.user = me
        moved += 1
    db.session.delete(user)
    db.session.commit()
    msg = (f'Deleted {user.display_name}; {moved} character(s) reassigned to you.'
           if moved else f'Deleted {user.display_name}.')
    return {'ok': True, 'message': msg, 'moved': moved}
