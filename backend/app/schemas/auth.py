from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import GSTIN, Email, Password


class RegisterRequest(BaseModel):
    """Sign-up creates a new organization and its first (admin) user."""

    organization_name: str = Field(min_length=2, max_length=255)
    organization_gstin: GSTIN | None = None
    full_name: str = Field(min_length=1, max_length=255)
    email: Email
    password: Password


class LoginRequest(BaseModel):
    email: Email
    # No length rules here: login must not reveal password policy details.
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # access token lifetime in seconds
