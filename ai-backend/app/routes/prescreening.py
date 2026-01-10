"""Pre-screening API endpoints for PDF analysis."""

import logging
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal

from app.lib.security import get_api_key
# Import from pdf_prescreening to trigger logger setup in __init__.py
from app.lib.pdf_prescreening import prescreening_analyze, PrescreeningResult, get_logger

# Use the shared prescreening logger
logger = get_logger()

router = APIRouter(prefix="/prescreening", dependencies=[Depends(get_api_key)])


class PrescreeningResponse(BaseModel):
    """API response for prescreening analysis."""
    status: Literal["text_layer_ok", "courtlistener_resolved", "ocr_resolved", "failed"]
    text: Optional[str] = None
    text_source: Optional[Literal["pdf_text", "courtlistener", "ocr"]] = None
    confidence: Optional[float] = None
    courtlistener_metadata: Optional[dict] = None
    warnings: list[str] = []
    error: Optional[str] = None
    
    # Debug info (optional)
    text_quality_score: Optional[float] = None
    identifiers_extracted: Optional[dict] = None


@router.post("/analyze", response_model=PrescreeningResponse)
async def analyze_pdf(file: UploadFile = File(...)) -> PrescreeningResponse:
    """
    Pre-screen a PDF for text extraction viability.
    
    For PDFs with a usable text layer, returns the extracted text immediately.
    For flattened/scanned PDFs, attempts to resolve via CourtListener first,
    then falls back to OCR if resolution fails.
    
    Returns:
        - status: One of "text_layer_ok", "courtlistener_resolved", "ocr_resolved", "failed"
        - text: Extracted or resolved text (if successful)
        - text_source: Source of the text ("pdf_text", "courtlistener", "ocr")
        - confidence: Confidence score (0-1)
        - courtlistener_metadata: If resolved via CourtListener, includes opinion details
        - warnings: Any warnings about the result
        - error: Error message if status is "failed"
    """
    # Validate file type
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    
    filename_lower = file.filename.lower()
    if not filename_lower.endswith(".pdf"):
        raise HTTPException(
            status_code=400, 
            detail="Only PDF files are supported for pre-screening"
        )
    
    try:
        # Read file bytes
        pdf_bytes = await file.read()
        
        if len(pdf_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")
        
        logger.info(f"Pre-screening PDF: {file.filename} ({len(pdf_bytes)} bytes)")
        
        # Run prescreening pipeline
        result: PrescreeningResult = await prescreening_analyze(pdf_bytes, file.filename)
        
        # Convert to API response
        response = PrescreeningResponse(
            status=result.status.value,
            text=result.text,
            text_source=result.text_source.value if result.text_source else None,
            confidence=result.confidence,
            courtlistener_metadata=result.courtlistener_metadata.model_dump() if result.courtlistener_metadata else None,
            warnings=result.warnings,
            error=result.error,
            text_quality_score=result.text_quality_score,
            identifiers_extracted=result.identifiers_extracted.model_dump() if result.identifiers_extracted else None,
        )
        
        logger.info(f"Pre-screening complete: status={response.status}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Pre-screening failed for {file.filename}")
        raise HTTPException(
            status_code=500,
            detail=f"Pre-screening failed: {str(e)}"
        )
