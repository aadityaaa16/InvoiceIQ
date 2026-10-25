"""API tests for reviewer corrections, approve/reject, audit logs and vendors."""

import uuid
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.enums import InvoiceStatus
from app.models.invoice import Invoice
from tests.factories import make_invoice, make_vendor
from tests.helpers import auth, create_user, login, register


async def _setup(client: AsyncClient, db: AsyncSession, **fields: Any) -> tuple[str, Invoice]:
    token = (await register(client))["access_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    org_id, user_id = uuid.UUID(me["organization_id"]), uuid.UUID(me["id"])
    vendor = await make_vendor(db, org_id)
    defaults: dict[str, Any] = {
        "vendor_id": vendor.id,
        "invoice_number": "INV-9",
        "subtotal": Decimal("1000"),
        "cgst": Decimal("90"),
        "sgst": Decimal("90"),
        "total_amount": Decimal("1200.00"),  # wrong on purpose: should be 1180
        "line_items": [{"description": "Rods", "amount": Decimal("1000")}],
    }
    invoice = await make_invoice(db, org_id, user_id, **(defaults | fields))
    return token, invoice


async def _audit(db: AsyncSession, invoice_id: uuid.UUID) -> list[AuditLog]:
    result = await db.execute(select(AuditLog).where(AuditLog.entity_id == invoice_id))
    return list(result.scalars())


async def test_correction_revalidates_and_is_audited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, invoice = await _setup(client, db_session)

    response = await client.patch(
        f"/api/v1/invoices/{invoice.id}", headers=auth(token), json={"total_amount": "1180.00"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["total_amount"] == "1180.00"
    assert response.json()["validation_errors"] == []  # rules re-ran on corrected data
    [log] = await _audit(db_session, invoice.id)
    assert log.action == "update"
    assert log.old_values == {"total_amount": "1200.00"}
    assert log.new_values == {"total_amount": "1180.00"}


async def test_correction_can_replace_line_items_and_vendor(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, invoice = await _setup(client, db_session)
    response = await client.patch(
        f"/api/v1/invoices/{invoice.id}",
        headers=auth(token),
        json={
            "vendor_gstin": "27aapfu0939f1zv",  # normalized to uppercase
            "line_items": [
                {"description": "Rods", "amount": "600"},
                {"description": "Wire", "amount": "400"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert [i["description"] for i in response.json()["line_items"]] == ["Rods", "Wire"]


async def test_approve_records_reviewer_and_audit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, invoice = await _setup(client, db_session)
    response = await client.post(f"/api/v1/invoices/{invoice.id}/approve", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert invoice.approved_by is not None
    assert invoice.approved_at is not None
    [log] = await _audit(db_session, invoice.id)
    assert log.action == "approve"


async def test_reject_with_reason(client: AsyncClient, db_session: AsyncSession) -> None:
    token, invoice = await _setup(client, db_session)
    response = await client.post(
        f"/api/v1/invoices/{invoice.id}/reject", headers=auth(token), json={"reason": "Not ours"}
    )
    assert response.json()["status"] == "rejected"
    [log] = await _audit(db_session, invoice.id)
    assert log.new_values == {"status": "rejected", "reason": "Not ours"}


async def test_cannot_review_invoice_not_awaiting_review(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, invoice = await _setup(client, db_session, status=InvoiceStatus.APPROVED)
    for method, path, body in [
        ("PATCH", "", {"total_amount": "1"}),
        ("POST", "/approve", None),
        ("POST", "/reject", {"reason": "x"}),
    ]:
        response = await client.request(
            method, f"/api/v1/invoices/{invoice.id}{path}", headers=auth(token), json=body
        )
        assert response.status_code == 409, path


async def test_approving_a_duplicate_is_blocked_by_database(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two copies awaiting review: the partial unique index stops the second approval."""
    token, first = await _setup(client, db_session)
    second = await make_invoice(
        db_session,
        first.organization_id,
        first.uploaded_by,
        vendor_id=first.vendor_id,
        invoice_number=first.invoice_number,
    )
    first_response = await client.post(f"/api/v1/invoices/{first.id}/approve", headers=auth(token))
    assert first_response.status_code == 200
    response = await client.post(f"/api/v1/invoices/{second.id}/approve", headers=auth(token))
    assert response.status_code == 409
    assert "already approved" in response.json()["error"]["message"]


async def test_uploader_cannot_review(client: AsyncClient, db_session: AsyncSession) -> None:
    admin_token, invoice = await _setup(client, db_session)
    await create_user(client, admin_token, "clerk@acme.com", role="uploader")
    token = await login(client, "clerk@acme.com")
    response = await client.post(f"/api/v1/invoices/{invoice.id}/approve", headers=auth(token))
    assert response.status_code == 403


async def test_patch_rejects_unknown_fields_and_negative_amounts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, invoice = await _setup(client, db_session)
    for body in [{"status": "approved"}, {"total_amount": "-5"}]:
        response = await client.patch(
            f"/api/v1/invoices/{invoice.id}", headers=auth(token), json=body
        )
        assert response.status_code == 422, body


async def test_vendor_endpoints_are_tenant_scoped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, invoice = await _setup(client, db_session)
    vendors = (await client.get("/api/v1/vendors", headers=auth(token))).json()
    assert [v["gstin"] for v in vendors] == ["27AAPFU0939F1ZV"]

    other = (await register(client, email="g@globex.com", organization_name="Globex"))[
        "access_token"
    ]
    assert (await client.get("/api/v1/vendors", headers=auth(other))).json() == []
    response = await client.get(f"/api/v1/vendors/{invoice.vendor_id}", headers=auth(other))
    assert response.status_code == 404
