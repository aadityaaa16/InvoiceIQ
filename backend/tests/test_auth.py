"""API tests for register, login, refresh and /me."""

from httpx import AsyncClient

from app.core.rate_limit import limiter
from tests.helpers import DEFAULT_PASSWORD, auth, create_user, login, register


async def test_register_creates_organization_and_admin(client: AsyncClient) -> None:
    tokens = await register(client, email="Owner@Acme.Com")
    assert tokens["token_type"] == "bearer"

    response = await client.get("/api/v1/auth/me", headers=auth(tokens["access_token"]))
    assert response.status_code == 200
    me = response.json()
    assert me["email"] == "owner@acme.com"  # normalized to lowercase
    assert me["role"] == "admin"
    assert me["organization"]["name"] == "Acme Traders"
    assert "hashed_password" not in me


async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    await register(client, email="dup@acme.com")
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "organization_name": "Other Co",
            "full_name": "X",
            "email": "DUP@acme.com",  # same email, different case
            "password": DEFAULT_PASSWORD,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_register_validation_error_format(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "organization_name": "Acme",
            "organization_gstin": "NOT-A-GSTIN",
            "full_name": "X",
            "email": "not-an-email",
            "password": "short",
        },
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    fields = {detail["field"] for detail in error["details"]}
    assert fields == {"organization_gstin", "email", "password"}


async def test_register_normalizes_valid_gstin(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "organization_name": "Acme",
            "organization_gstin": " 27aapfu0939f1zv ",
            "full_name": "X",
            "email": "gst@acme.com",
            "password": DEFAULT_PASSWORD,
        },
    )
    assert response.status_code == 201
    me = await client.get("/api/v1/auth/me", headers=auth(response.json()["access_token"]))
    assert me.json()["organization"]["gstin"] == "27AAPFU0939F1ZV"


async def test_login_success(client: AsyncClient) -> None:
    await register(client, email="login@acme.com")
    token = await login(client, "LOGIN@acme.com")
    response = await client.get("/api/v1/auth/me", headers=auth(token))
    assert response.status_code == 200


async def test_login_wrong_password_and_unknown_email_look_identical(client: AsyncClient) -> None:
    await register(client, email="real@acme.com")
    wrong_password = await client.post(
        "/api/v1/auth/login", json={"email": "real@acme.com", "password": "WrongPass123"}
    )
    unknown_email = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@acme.com", "password": "WrongPass123"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    # Same message: the response must not reveal which emails are registered.
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.headers["WWW-Authenticate"] == "Bearer"


async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_me_rejects_garbage_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me", headers=auth("not.a.jwt"))
    assert response.status_code == 401


async def test_refresh_rotates_tokens_and_rejects_reuse(client: AsyncClient) -> None:
    tokens = await register(client, email="refresh@acme.com")

    first = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert first.status_code == 200
    new_tokens = first.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # Replaying the old refresh token (e.g. a stolen copy) must fail.
    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401
    assert "already been used" in replay.json()["error"]["message"]

    # The new one still works.
    second = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert second.status_code == 200


async def test_access_token_cannot_be_used_to_refresh(client: AsyncClient) -> None:
    tokens = await register(client, email="mixup@acme.com")
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert response.status_code == 401


async def test_deactivated_user_is_locked_out_immediately(client: AsyncClient) -> None:
    admin = await register(client, email="boss@acme.com")
    user = await create_user(client, admin["access_token"], "leaver@acme.com")
    user_token = await login(client, "leaver@acme.com")

    await client.patch(
        f"/api/v1/users/{user['id']}",
        headers=auth(admin["access_token"]),
        json={"is_active": False},
    )

    # Existing access token stops working at once (user is re-checked on every request)...
    me = await client.get("/api/v1/auth/me", headers=auth(user_token))
    assert me.status_code == 401
    # ...and they cannot log in again.
    relogin = await client.post(
        "/api/v1/auth/login", json={"email": "leaver@acme.com", "password": DEFAULT_PASSWORD}
    )
    assert relogin.status_code == 401


async def test_login_is_rate_limited(client: AsyncClient) -> None:
    limiter.enabled = True
    limiter.reset()
    try:
        body = {"email": "brute@acme.com", "password": "guess-1234"}
        codes = [(await client.post("/api/v1/auth/login", json=body)).status_code for _ in range(6)]
        assert codes[:5] == [401] * 5  # limit is 5/minute
        assert codes[5] == 429
    finally:
        limiter.enabled = False
        limiter.reset()
