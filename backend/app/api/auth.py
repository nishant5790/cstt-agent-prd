"""Auth routes: register, login, current-user. Email/password with JWT bearer tokens."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import current_user
from app.auth import users as user_store
from app.auth.security import create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class CredentialsIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def _issue(rec: dict) -> TokenOut:
    token = create_access_token(sub=rec["id"], email=rec["email"])
    return TokenOut(access_token=token, user=user_store.public_user(rec))


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: CredentialsIn) -> TokenOut:
    try:
        rec = user_store.create_user(str(body.email), body.password)
    except user_store.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _issue(rec)


@router.post("/login", response_model=TokenOut)
def login(body: CredentialsIn) -> TokenOut:
    try:
        rec = user_store.authenticate(str(body.email), body.password)
    except user_store.AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    return _issue(rec)


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user
