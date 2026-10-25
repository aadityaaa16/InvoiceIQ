"""API tests for user management, role-based access and tenant isolation."""

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers import auth, create_user, login, register


async def test_admin_creates_user_in_own_organization(client: AsyncClient) -> None:
    admin = await register(client, email="admin@one.com")
    user = await create_user(client, admin["access_token"], "rev@one.com", role="reviewer")
    me = (await client.get("/api/v1/auth/me", headers=auth(admin["access_token"]))).json()

    assert user["role"] == "reviewer"
    assert user["organization_id"] == me["organization_id"]
    assert "hashed_password" not in user


async def test_new_user_defaults_to_uploader_role(client: AsyncClient) -> None:
    admin = await register(client, email="admin@defaults.com")
    response = await client.post(
        "/api/v1/users",
        headers=auth(admin["access_token"]),
        json={"email": "new@defaults.com", "full_name": "New", "password": "Str0ngPassw0rd!"},
    )
    assert response.json()["role"] == "uploader"


@pytest.mark.parametrize("role", ["reviewer", "uploader"])
async def test_non_admins_cannot_manage_users(client: AsyncClient, role: str) -> None:
    admin = await register(client, email=f"admin-{role}@rbac.com")
    await create_user(client, admin["access_token"], f"{role}@rbac.com", role=role)
    token = await login(client, f"{role}@rbac.com")

    assert (await client.get("/api/v1/users", headers=auth(token))).status_code == 403
    response = await client.post(
        "/api/v1/users",
        headers=auth(token),
        json={"email": "x@rbac.com", "full_name": "X", "password": "Str0ngPassw0rd!"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_users_list_is_scoped_to_organization(client: AsyncClient) -> None:
    acme = await register(client, email="admin@acme.com", organization_name="Acme")
    globex = await register(client, email="admin@globex.com", organization_name="Globex")
    await create_user(client, acme["access_token"], "staff@acme.com")

    acme_emails = {
        u["email"]
        for u in (await client.get("/api/v1/users", headers=auth(acme["access_token"]))).json()
    }
    globex_emails = {
        u["email"]
        for u in (await client.get("/api/v1/users", headers=auth(globex["access_token"]))).json()
    }
    assert acme_emails == {"admin@acme.com", "staff@acme.com"}
    assert globex_emails == {"admin@globex.com"}


async def test_admin_cannot_update_user_in_another_organization(client: AsyncClient) -> None:
    acme = await register(client, email="admin@acme2.com", organization_name="Acme")
    globex = await register(client, email="admin@globex2.com", organization_name="Globex")
    victim = await create_user(client, acme["access_token"], "victim@acme2.com")

    response = await client.patch(
        f"/api/v1/users/{victim['id']}",
        headers=auth(globex["access_token"]),
        json={"role": "admin"},
    )
    # 404, not 403: other tenants' ids must look like they do not exist.
    assert response.status_code == 404


async def test_admin_updates_role(client: AsyncClient) -> None:
    admin = await register(client, email="admin@promote.com")
    user = await create_user(client, admin["access_token"], "u@promote.com")
    response = await client.patch(
        f"/api/v1/users/{user['id']}",
        headers=auth(admin["access_token"]),
        json={"role": "reviewer", "full_name": "Promoted"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "reviewer"
    assert response.json()["full_name"] == "Promoted"


async def test_role_change_applies_to_existing_token(client: AsyncClient) -> None:
    admin = await register(client, email="admin@demote.com")
    user = await create_user(client, admin["access_token"], "u@demote.com", role="admin")
    user_token = await login(client, "u@demote.com")
    assert (await client.get("/api/v1/users", headers=auth(user_token))).status_code == 200

    await client.patch(
        f"/api/v1/users/{user['id']}",
        headers=auth(admin["access_token"]),
        json={"role": "uploader"},
    )
    # Same token, but the role is read from the DB on each request.
    assert (await client.get("/api/v1/users", headers=auth(user_token))).status_code == 403


@pytest.mark.parametrize("change", [{"role": "reviewer"}, {"is_active": False}])
async def test_admin_cannot_lock_themselves_out(
    client: AsyncClient, change: dict[str, object]
) -> None:
    admin = await register(client, email=f"admin-{len(str(change))}@lock.com")
    me = (await client.get("/api/v1/auth/me", headers=auth(admin["access_token"]))).json()
    response = await client.patch(
        f"/api/v1/users/{me['id']}", headers=auth(admin["access_token"]), json=change
    )
    assert response.status_code == 400


async def test_update_unknown_user_returns_404(client: AsyncClient) -> None:
    admin = await register(client, email="admin@missing.com")
    response = await client.patch(
        f"/api/v1/users/{uuid.uuid4()}",
        headers=auth(admin["access_token"]),
        json={"role": "reviewer"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
