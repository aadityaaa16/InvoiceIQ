"""Import every model here so Base.metadata knows about all tables.

Alembic autogenerate compares Base.metadata with the database; a model that is
never imported would be invisible to it and silently left out of migrations.
"""

from app.models.audit_log import AuditLog
from app.models.enums import InvoiceStatus, MatchStatus, ReconciliationStatus, UserRole
from app.models.invoice import Invoice, InvoiceLineItem
from app.models.organization import Organization
from app.models.reconciliation import ReconciliationResult, ReconciliationRun
from app.models.user import User
from app.models.vendor import Vendor

__all__ = [
    "AuditLog",
    "Invoice",
    "InvoiceLineItem",
    "InvoiceStatus",
    "MatchStatus",
    "Organization",
    "ReconciliationResult",
    "ReconciliationRun",
    "ReconciliationStatus",
    "User",
    "UserRole",
    "Vendor",
]
