"""
Main FastAPI application for Liberty Card Reconciliation.
"""
from fastapi import HTTPException, BackgroundTasks, APIRouter
from datetime import datetime, timedelta, date
from typing import Optional
import json

from card_reconciliation.config import settings
from card_reconciliation.models.schemas import (
    ReconciliationRequest,
    ReconciliationResponse,
    MetricsResponse,
    HealthResponse
)
from card_reconciliation.services.google_sheets_service import GoogleSheetsService
from card_reconciliation.services.reconciliation_service import ReconciliationService
from card_reconciliation.services.ai_service import AIService

# Router for inclusion in the main API app
router = APIRouter()


@router.get("/", tags=["Root"])
async def root():
    """Root endpoint."""
    return {
        "message": "Liberty Card Reconciliation API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint to verify service status and dependencies.
    """
    google_sheets_connected = False
    google_sheets_error = None
    openai_configured = bool(settings.openai_api_key)
    
    try:
        # Test Google Sheets connection
        sheets_service = GoogleSheetsService()
        google_sheets_connected = True
    except Exception as e:
        google_sheets_error = str(e)
    
    # Create health status message
    if google_sheets_connected:
        status = "healthy"
        message = "Service is running"
    else:
        status = "degraded"
        if google_sheets_error:
            message = f"Google Sheets not connected: {google_sheets_error}"
        else:
            message = "Google Sheets connection failed"
    
    return HealthResponse(
        status=status,
        message=message,
        google_sheets_connected=google_sheets_connected,
        openai_configured=openai_configured
    )


@router.post("/reconciliation/run", response_model=ReconciliationResponse, tags=["Reconciliation"])
async def run_reconciliation(
    request: ReconciliationRequest,
    background_tasks: BackgroundTasks,
    debug: bool = False
):
    """
    Run the complete reconciliation process.
    
    This endpoint:
    1. Loads data from Google Sheets
    2. Processes card transactions
    3. Performs settlement reconciliation
    4. Analyzes bank statements
    5. Generates metrics
    6. Creates AI summary
    7. Saves results back to Google Sheets
    
    Args:
        request: ReconciliationRequest with optional run_date and days_offset
        
    Returns:
        ReconciliationResponse with metrics and AI summary
    """
    recon_service = None
    try:
        # Determine run date
        if request.run_date:
            parts = request.run_date.split("-")
            if len(parts) != 3:
                raise ValueError("run_date must be in YYYY-MM-DD format")
            year, month, day = parts
            if not (year.isdigit() and month.isdigit() and day.isdigit()):
                raise ValueError("run_date must be numeric in YYYY-MM-DD format")
            normalized_run_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            run_date = datetime.strptime(normalized_run_date, "%Y-%m-%d").date()
        else:
            run_date = (datetime.today() - timedelta(days=request.days_offset)).date()
        
        # Step 1: Load data from Google Sheets
        sheets_service = GoogleSheetsService()
        sheets_data = sheets_service.load_all_sheets()
        
        # Step 2: Run reconciliation
        recon_service = ReconciliationService(sheets_data, run_date)
        results = recon_service.run_full_reconciliation()
        
        # Step 3: Save metrics to file
        metrics_path = recon_service.save_metrics_to_file()
        
        # Step 4: Generate AI summary
        ai_service = AIService()
        ai_summary = ai_service.generate_summary(results['metrics'])
        
        # Step 5: Write AI summary to Google Sheets (in background)
        background_tasks.add_task(
            sheets_service.write_summary_to_sheet,
            ai_summary,
            run_date
        )
        
        # Step 6: Push datasets to Google Sheets (in background)
        output_datasets = recon_service.get_output_datasets()
        
        def push_datasets_to_sheets():
            for sheet_name, df in output_datasets.items():
                worksheet = sheets_service.get_or_create_worksheet(sheet_name)
                sheets_service.append_df_to_sheet(worksheet, df)
        
        background_tasks.add_task(push_datasets_to_sheets)
        
        # Prepare response
        return ReconciliationResponse(
            status="success",
            message="Reconciliation completed successfully",
            run_date=str(run_date),
            metrics=MetricsResponse(**results['metrics']),
            ai_summary=ai_summary,
            metrics_file_path=metrics_path,
            debug=recon_service.get_debug_info() if debug else None
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        if debug and recon_service is not None:
            import traceback
            detail = {
                "message": f"Reconciliation failed: {str(e)}",
                "traceback": traceback.format_exc(),
                "debug": recon_service.get_debug_info()
            }
        else:
            detail = f"Reconciliation failed: {str(e)}"
        raise HTTPException(status_code=500, detail=detail)


@router.get("/metrics/{run_date}", response_model=MetricsResponse, tags=["Metrics"])
async def get_metrics(run_date: str):
    """
    Retrieve metrics for a specific date.
    
    Args:
        run_date: Date in format YYYY-MM-DD
        
    Returns:
        MetricsResponse with reconciliation metrics
    """
    try:
        # Validate date format
        run_date_obj = datetime.strptime(run_date, "%Y-%m-%d").date()
        
        # Load metrics from file
        metrics_path = f"{settings.output_dir}/metrics_{run_date}.json"
        
        with open(metrics_path, 'r') as f:
            metrics = json.load(f)
        
        return MetricsResponse(**metrics)
        
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Metrics not found for date {run_date}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving metrics: {str(e)}")


@router.get("/metrics/latest", response_model=MetricsResponse, tags=["Metrics"])
async def get_latest_metrics():
    """
    Retrieve the most recent metrics.
    
    Returns:
        MetricsResponse with the latest reconciliation metrics
    """
    try:
        import os
        import glob
        
        # Find all metrics files
        metrics_files = glob.glob(f"{settings.output_dir}/metrics_*.json")
        
        if not metrics_files:
            raise HTTPException(status_code=404, detail="No metrics found")
        
        # Get the most recent file
        latest_file = max(metrics_files, key=os.path.getctime)
        
        with open(latest_file, 'r') as f:
            metrics = json.load(f)
        
        return MetricsResponse(**metrics)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving latest metrics: {str(e)}")


@router.get("/config", tags=["Configuration"])
async def get_config():
    """
    Get current API configuration (non-sensitive values only).
    
    Returns:
        Dictionary with configuration settings
    """
    return {
        "spreadsheet_id": settings.spreadsheet_id,
        "ai_model": settings.ai_model,
        "merchant_ids": {
            "interswitch_unity": settings.merchant_id_interswitch_unity,
            "nibss_unity": settings.merchant_id_nibss_unity,
            "nibss_parallex": settings.merchant_id_nibss_parallex
        },
        "sheet_names": {
            "card_transaction": settings.sheet_card_transaction,
            "nibss_settlement": settings.sheet_nibss_settlement,
            "isw_settlement": settings.sheet_isw_settlement,
            "parallex_nibss": settings.sheet_parallex_nibss,
            "bank_unity": settings.sheet_bank_unity,
            "bank_parallex": settings.sheet_bank_parallex,
            "ai_summary": settings.sheet_ai_summary
        }
    }
