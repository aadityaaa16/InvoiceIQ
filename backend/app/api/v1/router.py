"""Combines all v1 routers. main.py mounts this under /api/v1."""

from fastapi import APIRouter

from app.api.v1 import auth, invoices, reconciliation, users, vendors

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(invoices.router)
api_router.include_router(vendors.router)
api_router.include_router(reconciliation.router)
api_router.include_router(reconciliation.dashboard_router)
