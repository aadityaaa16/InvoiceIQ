"""Small helpers that keep tests short and readable."""

from typing import Any

from httpx import AsyncClient

DEFAULT_PASSWORD = "Str0ngPassw0rd!"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(
    client: AsyncClient,
    email: str = "admin@acme.com",
    organization_name: str = "Acme Traders",
    password: str = DEFAULT_PASSWORD,
) -> dict[str, Any]:
    """Register a new organization + admin; returns the token pair."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "organization_name": organization_name,
            "full_name": "Asha Admin",
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login(client: AsyncClient, email: str, password: str = DEFAULT_PASSWORD) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def create_user(
    client: AsyncClient, admin_token: str, email: str, role: str = "uploader"
) -> dict[str, Any]:
    response = await client.post(
        "/api/v1/users",
        headers=auth(admin_token),
        json={"email": email, "full_name": "Test User", "password": DEFAULT_PASSWORD, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()
