"""User management (admin only)."""

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import AdminUser, DbSession
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def get_user_service(db: DbSession) -> UserService:
    return UserService(db)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


# response_model converts the returned ORM object into UserRead, which has no
# hashed_password field, so the hash can never be serialized into a response.
@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserRead)
async def create_user(data: UserCreate, admin: AdminUser, service: UserServiceDep) -> User:
    return await service.create_user(admin, data)


@router.get("", response_model=list[UserRead])
async def list_users(admin: AdminUser, service: UserServiceDep) -> Sequence[User]:
    return await service.list_users(admin)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID, data: UserUpdate, admin: AdminUser, service: UserServiceDep
) -> User:
    return await service.update_user(admin, user_id, data)
