from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str
    ttl_hours: Optional[int] = Field(default=None, ge=1, le=24 * 30)


class SetupRequest(BaseModel):
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class RecoverGenerateRequest(BaseModel):
    username: str = Field(min_length=1)


class RecoverResetRequest(BaseModel):
    username: str
    code: str
    new_password: str
    confirm_password: str


class UserCreate(BaseModel):
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    password: str = Field(min_length=1)
    role: str = 'player'


class UserEdit(BaseModel):
    username: str = Field(min_length=1)
    display_name: str = Field(min_length=1)


class UserResetPassword(BaseModel):
    new_password: str = Field(min_length=1)
