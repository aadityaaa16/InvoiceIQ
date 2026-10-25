"""Reconciliation: matching logic, GSTR-2B parsing, API, and dashboard stats."""

import io
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.enums import InvoiceStatus, MatchStatus
from app.services.gstr2b_parser import GstrRecord, parse_excel, parse_json
from app.services.reconciliation import BookEntry, normalize_invoice_number, reconcile
from tests.factories import make_invoice, make_vendor
from tests.helpers import auth, create_user, login, register

D = Decimal
GSTIN = "27AAPFU0939F1ZV"


def _record(number: str, value: str, gstin: str = GSTIN) -> GstrRecord:
    return GstrRecord(
        supplier_gstin=gstin,
        invoice_number=number,
        invoice_value=D(value),
        cgst=D("90"),
        sgst=D("90"),
    )


def _book(number: str, total: str) -> BookEntry:
    return BookEntry(uuid.uuid4(), GSTIN, number, D(total), D("180"))


# ---------------------------------------------------------------- matching (pure)


def test_reconcile_classifies_all_four_cases() -> None:
    matched, mismatch, only_books = _book("A1", "1180"), _book("A2", "1180"), _book("A3", "500")
    gstr = [_record("A1", "1180.40"), _record("A2", "1000"), _record("A9", "300")]

    results = {r.status: r for r in reconcile([matched, mismatch, only_books], gstr, D("1"))}

    assert results[MatchStatus.MATCHED].invoice_id == matched.invoice_id  # within tolerance
    assert results[MatchStatus.AMOUNT_MISMATCH].difference == D("180")
    assert results[MatchStatus.MISSING_IN_GSTR].invoice_id == only_books.invoice_id
    assert results[MatchStatus.MISSING_IN_BOOKS].invoice_id is None


def test_invoice_numbers_match_despite_formatting() -> None:
    assert normalize_invoice_number("inv/001") == normalize_invoice_number("INV-001")
    [result] = reconcile([_book("INV-001", "1180")], [_record("inv 001", "1180")], D("1"))
    assert result.status == MatchStatus.MATCHED


def test_same_number_from_different_supplier_does_not_match() -> None:
    results = reconcile(
        [_book("A1", "1180")], [_record("A1", "1180", gstin="29AAACR5055K1Z3")], D("1")
    )
    assert {r.status for r in results} == {
        MatchStatus.MISSING_IN_BOOKS,
        MatchStatus.MISSING_IN_GSTR,
    }


# ---------------------------------------------------------------- parsing


def _portal_json(*invoices: dict[str, Any]) -> bytes:
    return json.dumps(
        {"data": {"docdata": {"b2b": [{"ctin": GSTIN, "trdnm": "Sharma", "inv": list(invoices)}]}}}
    ).encode()


def test_parse_portal_json() -> None:
    [record] = parse_json(
        _portal_json({"inum": "A1", "dt": "15-09-2026", "val": 1180.5, "cgst": 90, "sgst": 90})
    )
    assert record.invoice_date == date(2026, 9, 15)
    assert record.invoice_value == D("1180.5")
    assert record.total_tax == D("180")


def test_parse_excel() -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["GSTIN", "Invoice Number", "Invoice Date", "Invoice Value", "CGST", "SGST"])
    sheet.append([GSTIN.lower(), "A1", "15/09/2026", 1180.1, 90, 90])
    sheet.append([None, None, None, None, None, None])  # blank row is skipped
    buffer = io.BytesIO()
    workbook.save(buffer)

    [record] = parse_excel(buffer.getvalue())
    assert record.supplier_gstin == GSTIN  # normalized
    assert record.invoice_value == D("1180.1")  # no float noise


@pytest.mark.parametrize(
    "content", [b"not json", b'{"something": "else"}', _portal_json({"dt": "15-09-2026"})]
)
def test_bad_json_is_rejected(content: bytes) -> None:
    with pytest.raises(Exception, match="(?i)json|record|b2b"):
        parse_json(content)


# ---------------------------------------------------------------- API


async def _org(client: AsyncClient, db: AsyncSession) -> tuple[str, uuid.UUID, uuid.UUID]:
    token = (await register(client))["access_token"]
    me = (await client.get("/api/v1/auth/me", headers=auth(token))).json()
    return token, uuid.UUID(me["organization_id"]), uuid.UUID(me["id"])


async def test_reconciliation_run_end_to_end(client: AsyncClient, db_session: AsyncSession) -> None:
    token, org_id, user_id = await _org(client, db_session)
    vendor = await make_vendor(db_session, org_id)
    approved = dict(
        status=InvoiceStatus.APPROVED, vendor_id=vendor.id, invoice_date=date(2026, 9, 10)
    )
    await make_invoice(
        db_session, org_id, user_id, invoice_number="A1", total_amount=D("1180"), **approved
    )
    await make_invoice(
        db_session,
        org_id,
        user_id,
        invoice_number="A2",
        total_amount=D("2360"),
        cgst=D("180"),
        sgst=D("180"),
        **approved,
    )
    # Different month and not approved: both must be ignored.
    await make_invoice(
        db_session,
        org_id,
        user_id,
        invoice_number="OLD",
        status=InvoiceStatus.APPROVED,
        vendor_id=vendor.id,
        invoice_date=date(2026, 8, 31),
    )
    await make_invoice(db_session, org_id, user_id, invoice_number="REV", vendor_id=vendor.id)

    gstr = _portal_json({"inum": "A1", "dt": "10-09-2026", "val": 1180, "cgst": 90, "sgst": 90})
    response = await client.post(
        "/api/v1/reconciliation/runs",
        headers=auth(token),
        data={"period": "2026-09"},
        files={"file": ("gstr2b.json", gstr, "application/json")},
    )

    assert response.status_code == 201, response.text
    run = response.json()
    assert run["summary"]["counts"] == {
        "matched": 1,
        "amount_mismatch": 0,
        "missing_in_gstr": 1,
        "missing_in_books": 0,
    }
    assert run["summary"]["itc_at_risk"] == "360.00"  # A2's tax can't be claimed yet

    results = await client.get(
        f"/api/v1/reconciliation/runs/{run['id']}/results?match_status=missing_in_gstr",
        headers=auth(token),
    )
    assert len(results.json()) == 1

    runs = await client.get("/api/v1/reconciliation/runs", headers=auth(token))
    assert [r["id"] for r in runs.json()] == [run["id"]]


async def test_reconciliation_validation_and_access(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, _, _ = await _org(client, db_session)
    file = {"file": ("gstr2b.json", _portal_json(), "application/json")}

    bad_period = await client.post(
        "/api/v1/reconciliation/runs", headers=auth(token), data={"period": "2026-13"}, files=file
    )
    assert bad_period.status_code == 422

    bad_file = await client.post(
        "/api/v1/reconciliation/runs",
        headers=auth(token),
        data={"period": "2026-09"},
        files={"file": ("gstr2b.csv", b"a,b", "text/csv")},
    )
    assert bad_file.status_code == 400

    await create_user(client, token, "clerk@acme.com", role="uploader")
    clerk = await login(client, "clerk@acme.com")
    forbidden = await client.post(
        "/api/v1/reconciliation/runs", headers=auth(clerk), data={"period": "2026-09"}, files=file
    )
    assert forbidden.status_code == 403

    other = (await register(client, email="g@globex.com", organization_name="Globex"))[
        "access_token"
    ]
    run = await client.post(
        "/api/v1/reconciliation/runs", headers=auth(token), data={"period": "2026-09"}, files=file
    )
    response = await client.get(
        f"/api/v1/reconciliation/runs/{run.json()['id']}/results", headers=auth(other)
    )
    assert response.status_code == 404


async def test_dashboard_stats(client: AsyncClient, db_session: AsyncSession) -> None:
    token, org_id, user_id = await _org(client, db_session)
    auto = await make_invoice(
        db_session,
        org_id,
        user_id,
        status=InvoiceStatus.APPROVED,
        invoice_date=date.today(),
        total_amount=D("1000"),
    )
    await make_invoice(db_session, org_id, user_id, status=InvoiceStatus.NEEDS_REVIEW)
    await make_invoice(db_session, org_id, user_id, status=InvoiceStatus.QUEUED)
    db_session.add(
        AuditLog(
            organization_id=org_id, entity_type="invoice", entity_id=auto.id, action="auto_approve"
        )
    )
    await db_session.flush()

    stats = (await client.get("/api/v1/dashboard/stats", headers=auth(token))).json()

    assert stats["total_invoices"] == 3
    assert stats["counts_by_status"]["approved"] == 1
    assert stats["counts_by_status"]["failed"] == 0  # every status present
    assert stats["auto_approval_rate"] == 0.5  # 1 of 2 processed invoices
    assert stats["approved_amount_this_month"] == "1000.00"
