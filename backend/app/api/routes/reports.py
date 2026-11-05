"""System resource diagnostic PDF report endpoints."""

import logging
from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError

from app.services.report_service import (
    SUPPORTED_REPORT_RANGES,
    SUPPORTED_REPORT_TYPES,
    ReportGenerationError,
    report_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])

VALID_RESOURCES = {"cpu", "memory", "disk", "network", "all", None}


@router.get(
    "/pdf",
    summary="Download comprehensive system resource diagnostic PDF report",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Downloadable PDF diagnostic report",
        },
        400: {"description": "Invalid date range or report type"},
        500: {"description": "PDF document compilation failure"},
        503: {"description": "Database telemetry storage failure"},
    },
)
def download_pdf_report(
    range: str = Query(
        default="24h",
        description="Report date range: 1h, 6h, 24h, 7d, 30d",
    ),
    type: str = Query(
        default="all",
        description="Report type: all, cpu_memory, disk_network, process_resource, alerts_anomaly, prediction_accuracy",
    ),
    resource: str | None = Query(
        default=None,
        description="Optional resource filter for backwards compatibility: cpu, memory, disk, network, all",
    ),
) -> Response:
    """Generate and download a comprehensive or specialized system resource diagnostic PDF report."""
    if range not in SUPPORTED_REPORT_RANGES:
        valid_ranges = ", ".join(SUPPORTED_REPORT_RANGES.keys())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date range: '{range}'. Supported ranges: {valid_ranges}",
        )

    if type not in SUPPORTED_REPORT_TYPES:
        valid_types = ", ".join(SUPPORTED_REPORT_TYPES.keys())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid report type: '{type}'. Supported types: {valid_types}",
        )

    if resource is not None and resource not in VALID_RESOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource filter: '{resource}'. Valid filters: cpu, memory, disk, network, all",
        )

    try:
        pdf_bytes, filename = report_service.generate_pdf_report(
            range_key=range, report_type=type, resource_filter=resource
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        logger.exception("Database error while compiling PDF report")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database failure during report generation",
        ) from exc
    except ReportGenerationError as exc:
        logger.exception("ReportLab PDF generation failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PDF generation failed",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error while compiling PDF report")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error during report generation",
        ) from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )
