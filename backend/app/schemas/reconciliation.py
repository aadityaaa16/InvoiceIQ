import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import InvoiceStatus, MatchStatus, ReconciliationStatus

PERIOD_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"  # YYYY-MM


class ReconciliationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period: str
    status: ReconciliationStatus
    summary: dict[str, Any] | None
    created_by: uuid.UUID
    created_at: datetime


class ReconciliationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID | None
    match_status: MatchStatus
    difference_amount: Decimal | None
    gstr_record: dict[str, Any] | None


class DashboardStats(BaseModel):
    total_invoices: int
    counts_by_status: dict[InvoiceStatus, int]
    auto_approval_rate: float | None  # share of processed invoices approved with no human
    avg_processing_seconds: float | None  # upload -> extraction finished
    approved_amount_this_month: Decimal
