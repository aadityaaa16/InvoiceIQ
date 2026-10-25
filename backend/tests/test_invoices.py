"""API tests for invoice upload, list, detail, status and file URL."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import InvoiceStatus
from tests.factories import make_invoice, make_vendor
from tests.fakes import FakeStorage, FakeTaskQueue
from tests.helpers import auth, create_user, login, register

PDF = b"%PDF-1.7\n fake invoice content"
PNG = b"\x89PNG\r\n\x1a\n fake image"


async def _me(client: AsyncClient, token: str) -> dict[str, Any]:
    response = await client.get("/api/v1/auth/me", headers=auth(token))
    return dict(response.json())


async def _upload(
    client: AsyncClient, token: str, content: bytes, filename: str = "invoice.pdf"
) -> Any:
    return await client.post(
        "/api/v1/invoices/upload",
        headers=auth(token),
        files={"file": (filename, content, "application/octet-stream")},
    )


# ---------------------------------------------------------------- upload


async def test_upload_stores_file_creates_row_and_enqueues(
    client: AsyncClient, storage: FakeStorage, task_queue: FakeTaskQueue
) -> None:
    token = (await register(client))["access_token"]
    me = await _me(client, token)

    response = await _upload(client, token, PDF, "Bill Sept.pdf")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["original_filename"] == "Bill Sept.pdf"
    invoice_id = uuid.UUID(body["id"])
    assert task_queue.enqueued == [invoice_id]

    key = f"{me['organization_id']}/invoices/{invoice_id}/original.pdf"
    assert storage.objects[key] == (PDF, "application/pdf")


async def test_upload_detects_type_from_content_not_extension(
    client: AsyncClient, storage: FakeStorage
) -> None:
    token = (await register(client))["access_token"]
    response = await _upload(client, token, PNG, "looks-like.pdf")
    assert response.status_code == 202
    detail = (
        await client.get(f"/api/v1/invoices/{response.json()['id']}", headers=auth(token))
    ).json()
    assert detail["file_type"] == "png"


async def test_upload_rejects_unsupported_file(client: AsyncClient, storage: FakeStorage) -> None:
    token = (await register(client))["access_token"]
    response = await _upload(client, token, b"MZ\x90\x00 an .exe renamed", "invoice.pdf")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_file_type"
    assert storage.objects == {}


async def test_upload_rejects_too_large_file(client: AsyncClient, storage: FakeStorage) -> None:
    token = (await register(client))["access_token"]
    too_big = PDF + b"0" * settings.max_upload_size_bytes
    response = await _upload(client, token, too_big)
    assert response.status_code == 413
    assert storage.objects == {}


async def test_upload_rejects_empty_file(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    response = await _upload(client, token, b"")
    assert response.status_code == 400


async def test_upload_sanitizes_path_in_filename(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    response = await _upload(client, token, PDF, "../../etc/passwd.pdf")
    assert response.json()["original_filename"] == "passwd.pdf"


async def test_upload_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/invoices/upload", files={"file": ("a.pdf", PDF, "application/pdf")}
    )
    assert response.status_code == 401


async def test_uploader_role_can_upload(client: AsyncClient) -> None:
    admin = (await register(client))["access_token"]
    await create_user(client, admin, "clerk@acme.com", role="uploader")
    token = await login(client, "clerk@acme.com")
    assert (await _upload(client, token, PDF)).status_code == 202


async def test_upload_marks_failed_when_queue_is_down(
    client: AsyncClient, task_queue: FakeTaskQueue
) -> None:
    token = (await register(client))["access_token"]
    task_queue.fail = True
    response = await _upload(client, token, PDF)
    # The file is safely stored; the invoice is marked failed so it can be retried.
    assert response.status_code == 202
    assert response.json()["status"] == "failed"
    assert "retry" in response.json()["failure_reason"]


# ---------------------------------------------------------------- list


async def test_list_paginates(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    for _ in range(5):
        await _upload(client, token, PDF)

    page1 = (await client.get("/api/v1/invoices?page=1&page_size=2", headers=auth(token))).json()
    page3 = (await client.get("/api/v1/invoices?page=3&page_size=2", headers=auth(token))).json()

    assert page1["total"] == 5
    assert page1["pages"] == 3
    assert len(page1["items"]) == 2
    assert len(page3["items"]) == 1


async def test_list_filters_by_status_vendor_and_date(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = (await register(client))["access_token"]
    me = await _me(client, token)
    org_id, user_id = uuid.UUID(me["organization_id"]), uuid.UUID(me["id"])
    vendor = await make_vendor(db_session, org_id)

    await make_invoice(
        db_session, org_id, user_id, status=InvoiceStatus.APPROVED, vendor_id=vendor.id
    )
    await make_invoice(db_session, org_id, user_id, status=InvoiceStatus.NEEDS_REVIEW)
    await make_invoice(
        db_session, org_id, user_id, status=InvoiceStatus.FAILED, invoice_date=date(2026, 1, 5)
    )

    async def count(query: str) -> int:
        response = await client.get(f"/api/v1/invoices?{query}", headers=auth(token))
        assert response.status_code == 200, response.text
        return int(response.json()["total"])

    assert await count("status=approved") == 1
    assert await count("status=approved&status=needs_review") == 2
    assert await count(f"vendor_id={vendor.id}") == 1
    assert await count("date_from=2026-09-01&date_to=2026-09-30") == 2


async def test_list_sorts_by_amount_with_nulls_last(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = (await register(client))["access_token"]
    me = await _me(client, token)
    org_id, user_id = uuid.UUID(me["organization_id"]), uuid.UUID(me["id"])
    for amount in ["500.00", None, "2500.00"]:
        await make_invoice(
            db_session, org_id, user_id, total_amount=Decimal(amount) if amount else None
        )

    response = await client.get(
        "/api/v1/invoices?sort_by=total_amount&sort_order=desc", headers=auth(token)
    )
    amounts = [item["total_amount"] for item in response.json()["items"]]
    assert amounts == ["2500.00", "500.00", None]  # money serialized as exact strings


async def test_list_rejects_bad_query_params(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    for query in [
        "sort_by=hashed_password",  # not whitelisted
        "page_size=1000",  # over the cap
        "date_from=2026-10-01&date_to=2026-09-01",  # inverted range
        "stauts=approved",  # typo: unknown params are rejected
    ]:
        response = await client.get(f"/api/v1/invoices?{query}", headers=auth(token))
        assert response.status_code == 422, query


async def test_list_is_scoped_to_organization(client: AsyncClient) -> None:
    acme = (await register(client, email="a@acme.com", organization_name="Acme"))["access_token"]
    globex = (await register(client, email="g@globex.com", organization_name="Globex"))[
        "access_token"
    ]
    await _upload(client, acme, PDF)

    response = await client.get("/api/v1/invoices", headers=auth(globex))
    assert response.json()["total"] == 0


# ---------------------------------------------------------------- detail / status / file


async def test_detail_includes_line_items_and_vendor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = (await register(client))["access_token"]
    me = await _me(client, token)
    org_id, user_id = uuid.UUID(me["organization_id"]), uuid.UUID(me["id"])
    vendor = await make_vendor(db_session, org_id)
    invoice = await make_invoice(
        db_session,
        org_id,
        user_id,
        vendor_id=vendor.id,
        line_items=[
            {"description": "Steel rods", "hsn_code": "7214", "amount": Decimal("1000.00")},
        ],
    )

    response = await client.get(f"/api/v1/invoices/{invoice.id}", headers=auth(token))
    assert response.status_code == 200
    detail = response.json()
    assert detail["vendor"]["name"] == "Sharma Distributors"
    assert detail["line_items"][0]["description"] == "Steel rods"
    assert detail["line_items"][0]["amount"] == "1000.00"


async def test_other_organization_gets_404_everywhere(client: AsyncClient) -> None:
    acme = (await register(client, email="a@acme.com", organization_name="Acme"))["access_token"]
    globex = (await register(client, email="g@globex.com", organization_name="Globex"))[
        "access_token"
    ]
    invoice_id = (await _upload(client, acme, PDF)).json()["id"]

    for path in ["", "/status", "/file"]:
        response = await client.get(f"/api/v1/invoices/{invoice_id}{path}", headers=auth(globex))
        assert response.status_code == 404, path


async def test_status_endpoint(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    invoice_id = (await _upload(client, token, PDF)).json()["id"]
    response = await client.get(f"/api/v1/invoices/{invoice_id}/status", headers=auth(token))
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert set(response.json()) == {"id", "status", "failure_reason", "updated_at"}


async def test_file_endpoint_returns_presigned_url(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    invoice_id = (await _upload(client, token, PDF)).json()["id"]
    response = await client.get(f"/api/v1/invoices/{invoice_id}/file", headers=auth(token))
    assert response.status_code == 200
    assert invoice_id in response.json()["url"]
    assert response.json()["expires_in"] == settings.PRESIGNED_URL_EXPIRE_SECONDS


async def test_unknown_invoice_returns_404(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    response = await client.get(f"/api/v1/invoices/{uuid.uuid4()}", headers=auth(token))
    assert response.status_code == 404


# ---------------------------------------------------------------- retry


async def test_retry_requeues_failed_invoice(
    client: AsyncClient, db_session: AsyncSession, task_queue: FakeTaskQueue
) -> None:
    token = (await register(client))["access_token"]
    me = await _me(client, token)
    invoice = await make_invoice(
        db_session,
        uuid.UUID(me["organization_id"]),
        uuid.UUID(me["id"]),
        status=InvoiceStatus.FAILED,
        failure_reason="OCR failed",
        retry_count=3,
    )

    response = await client.post(f"/api/v1/invoices/{invoice.id}/retry", headers=auth(token))

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["failure_reason"] is None
    assert task_queue.enqueued == [invoice.id]


async def test_retry_rejects_non_failed_invoice(
    client: AsyncClient, task_queue: FakeTaskQueue
) -> None:
    token = (await register(client))["access_token"]
    invoice_id = (await _upload(client, token, PDF)).json()["id"]  # status: queued

    response = await client.post(f"/api/v1/invoices/{invoice_id}/retry", headers=auth(token))

    assert response.status_code == 409
    assert len(task_queue.enqueued) == 1  # only the original upload


async def test_retry_other_organization_returns_404(client: AsyncClient) -> None:
    acme = (await register(client, email="a@acme.com", organization_name="Acme"))["access_token"]
    globex = (await register(client, email="g@globex.com", organization_name="Globex"))[
        "access_token"
    ]
    invoice_id = (await _upload(client, acme, PDF)).json()["id"]
    response = await client.post(f"/api/v1/invoices/{invoice_id}/retry", headers=auth(globex))
    assert response.status_code == 404
