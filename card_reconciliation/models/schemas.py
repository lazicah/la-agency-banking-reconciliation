"""
Pydantic models for request/response schemas.
"""
from typing import Optional, Dict, Any
from datetime import date
from pydantic import BaseModel


class ReconciliationRequest(BaseModel):
    """Request model for reconciliation process."""
    run_date: Optional[str] = None  # Expected format: YYYY-MM-DD, defaults to today - 18 days
    days_offset: Optional[int] = 18  # Number of days to offset from today


class ChannelMetrics(BaseModel):
    """Metrics for a specific channel."""
    revenue: float
    settlement: float
    charge_back: float
    unsettled_claim: float


class ISWBankMetrics(BaseModel):
    """Metrics for ISW Bank."""
    charge_back: float
    unsettled_claim: float


class MetricsResponse(BaseModel):
    """Response model for metrics."""
    run_date: str
    total_revenue: float
    total_settlement: float
    total_settlement_charge_back: float
    total_settlement_unsettled_claims: float
    total_bank_isw_unsettled_claims: float
    total_bank_isw_charge_back: float
    channels: Dict[str, Any]


class ReconciliationResponse(BaseModel):
    """Response model for reconciliation process."""
    status: str
    message: str
    run_date: str
    metrics: MetricsResponse
    ai_summary: Optional[str] = None
    metrics_file_path: str
    debug: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    message: str
    google_sheets_connected: bool
    openai_configured: bool
