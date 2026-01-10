"""Pre-screening pipeline orchestrator."""

import logging
from typing import Optional

from .models import (
    PrescreeningStatus,
    TextSource,
    PrescreeningResult,
    Identifiers,
    TextExtractionResult,
)
from .text_extractor import extract_first_page_text
from .gemini_analyzer import analyze_pdf_images
from .courtlistener_client import CourtListenerClient, extract_citations_from_text
from .ilovepdf_client import ILovePdfClient, is_ilovepdf_configured

# Use the shared prescreening logger (configured in __init__.py)
logger = logging.getLogger("prescreening")


def _text_looks_readable(text: str, sample_size: int = 500) -> bool:
    """
    Quick heuristic check if text looks like readable English.
    
    Checks for:
    - Common English words
    - No garbage patterns like (cid:X)
    - Reasonable word structure
    """
    sample = text[:sample_size].lower()
    
    # Check for garbage patterns
    if "(cid:" in sample:
        return False
    
    # Check for common English words (case-insensitive)
    common_words = ["the", "and", "of", "to", "in", "for", "that", "is", "was", "court"]
    words_found = sum(1 for word in common_words if f" {word} " in f" {sample} ")
    
    # If we find at least 3 common words, it's likely readable
    return words_found >= 3


async def prescreening_analyze(
    pdf_bytes: bytes, 
    filename: str,
    skip_courtlistener: bool = False,
) -> PrescreeningResult:
    """
    Main pre-screening pipeline entry point.
    
    Flow:
    1. Extract text via iLovePDF (first few pages for quality check)
    2. If extraction is clearly good (high quality), skip Gemini → text_layer_ok
    3. If borderline, send to Gemini for visual comparison
    4. If Gemini says flattened → try CourtListener resolution
    5. If CourtListener fails → fall back to iLovePDF OCR
    
    Args:
        pdf_bytes: Raw PDF file bytes
        filename: Original filename (for logging)
        skip_courtlistener: Skip CourtListener resolution (for testing)
        
    Returns:
        PrescreeningResult with status and text
    """
    logger.info(f"Starting pre-screening for: {filename}")
    warnings: list[str] = []
    extraction_result: Optional[TextExtractionResult] = None
    
    # Check if iLovePDF is configured
    if not is_ilovepdf_configured():
        logger.error("iLovePDF API keys not configured")
        return PrescreeningResult(
            status=PrescreeningStatus.FAILED,
            text=None,
            text_source=None,
            confidence=0.0,
            warnings=[],
            error="iLovePDF API keys not configured. Set ILOVEPDF_PUBLIC_KEY and ILOVEPDF_SECRET_KEY.",
        )
    
    # Step 1: Extract text via iLovePDF (first few pages for quality assessment)
    logger.info("Step 1: Extracting text via iLovePDF")
    try:
        ilovepdf = ILovePdfClient()
        extraction_result = ilovepdf.extract_text(pdf_bytes)
    except Exception as e:
        logger.error(f"iLovePDF extraction failed: {e}")
        return PrescreeningResult(
            status=PrescreeningStatus.FAILED,
            text=None,
            text_source=None,
            confidence=0.0,
            warnings=[],
            error=f"Text extraction failed: {str(e)}",
        )
    
    logger.info(
        f"Extraction result: {extraction_result.total_chars} chars, "
        f"quality={extraction_result.quality_score:.2f}"
    )
    
    # Step 1b: Fast path - if extraction is CLEARLY good, skip Gemini entirely
    # High quality score + readable text means the text layer is definitely usable
    # This saves API calls and time for obviously good PDFs
    if (
        extraction_result.quality_score >= 0.95
        and extraction_result.total_chars > 1000
        and _text_looks_readable(extraction_result.text)
    ):
        logger.info(
            "Fast path: extraction is clearly good (quality >= 0.95, readable text), "
            "skipping Gemini verification"
        )
        return PrescreeningResult(
            status=PrescreeningStatus.TEXT_LAYER_OK,
            text=extraction_result.text,
            text_source=TextSource.PDF_TEXT,
            confidence=extraction_result.quality_score,
            warnings=extraction_result.reasons,
            text_quality_score=extraction_result.quality_score,
            identifiers_extracted=None,  # Didn't use Gemini, so no identifiers
        )
    
    # Step 2: Send images + extracted text to Gemini for visual comparison
    # Gemini compares visual text against extracted text to detect garbage
    # (e.g., "(cid:X)" patterns that look like garbage but pass basic heuristics)
    logger.info("Step 2: Sending to Gemini for visual vs extracted text comparison")
    
    gemini_result = await analyze_pdf_images(
        pdf_bytes, 
        extracted_text=extraction_result.text
    )
    
    logger.info(
        f"Gemini analysis: is_flattened={gemini_result.is_flattened}, "
        f"confidence={gemini_result.confidence:.2f}"
    )
    
    if gemini_result.identifiers:
        logger.info(f"Gemini extracted identifiers: {gemini_result.identifiers.model_dump()}")
    
    # Step 3: If Gemini says extraction is usable (NOT flattened), return it
    if not gemini_result.is_flattened and gemini_result.confidence >= 0.7:
        logger.info("Gemini confirms text extraction is usable, returning pdf_text result")
        
        # Verify the extraction has reasonable content
        if extraction_result.total_chars > 500:
            return PrescreeningResult(
                status=PrescreeningStatus.TEXT_LAYER_OK,
                text=extraction_result.text,
                text_source=TextSource.PDF_TEXT,
                confidence=gemini_result.confidence,
                warnings=extraction_result.reasons,
                text_quality_score=extraction_result.quality_score,
                identifiers_extracted=gemini_result.identifiers,
            )
        else:
            logger.warning(
                f"Gemini said usable but extraction too short ({extraction_result.total_chars} chars). "
                f"Proceeding to resolution."
            )
            warnings.append("Text extraction too short despite appearing valid")
    else:
        logger.info(
            f"Gemini says extraction is NOT usable (is_flattened={gemini_result.is_flattened}, "
            f"confidence={gemini_result.confidence:.2f})"
        )
    
    # Step 3b: PDF is flattened - try CourtListener resolution
    identifiers = gemini_result.identifiers or Identifiers()
    
    # Try to extract citations from first page text (even flattened PDFs sometimes have some text)
    first_page_text = extract_first_page_text(pdf_bytes)
    if first_page_text:
        logger.info(f"First page text extracted: {len(first_page_text)} chars")
        page1_citations = extract_citations_from_text(first_page_text)
        if page1_citations:
            logger.info(f"Found citations in first page: {page1_citations}")
            identifiers.citations = list(set(identifiers.citations + page1_citations))
    
    logger.info(f"Final identifiers for resolution: {identifiers.model_dump()}")
    
    if not skip_courtlistener and identifiers.has_sufficient_data():
        logger.info("Step 3: Attempting CourtListener resolution")
        
        client = CourtListenerClient()
        resolution_result = await client.resolve(identifiers)
        
        if resolution_result.success and resolution_result.text:
            logger.info(
                f"CourtListener resolution successful: {resolution_result.metadata.case_name}"
            )
            
            return PrescreeningResult(
                status=PrescreeningStatus.COURTLISTENER_RESOLVED,
                text=resolution_result.text,
                text_source=TextSource.COURTLISTENER,
                confidence=resolution_result.metadata.resolver_confidence,
                courtlistener_metadata=resolution_result.metadata,
                warnings=warnings,
                text_quality_score=extraction_result.quality_score if extraction_result else 0.0,
                identifiers_extracted=identifiers,
            )
        else:
            logger.info(
                f"CourtListener resolution failed: {resolution_result.failure_reason}"
            )
            warnings.append(f"CourtListener: {resolution_result.failure_reason}")
    else:
        if skip_courtlistener:
            logger.info("Skipping CourtListener (disabled)")
        else:
            logger.info("Insufficient identifiers for CourtListener resolution")
            warnings.append("Could not extract sufficient identifiers for resolution")
    
    # Step 4: Fall back to iLovePDF OCR
    logger.info("Step 4: Falling back to iLovePDF OCR")
    
    try:
        ocr_text = ilovepdf.ocr_pdf(pdf_bytes)
    except Exception as e:
        logger.error(f"iLovePDF OCR failed: {e}")
        ocr_text = None
    
    if ocr_text and len(ocr_text) > 500:
        logger.info(f"OCR successful: {len(ocr_text)} chars extracted")
        return PrescreeningResult(
            status=PrescreeningStatus.OCR_RESOLVED,
            text=ocr_text,
            text_source=TextSource.OCR,
            confidence=0.8,  # iLovePDF OCR has good confidence
            warnings=warnings,
            text_quality_score=extraction_result.quality_score if extraction_result else 0.0,
            identifiers_extracted=identifiers,
        )
    
    # Everything failed
    logger.error("Pre-screening failed: no usable text could be extracted")
    return PrescreeningResult(
        status=PrescreeningStatus.FAILED,
        text=None,
        text_source=None,
        confidence=0.0,
        warnings=warnings,
        error="No usable text could be extracted from this PDF",
        text_quality_score=extraction_result.quality_score if extraction_result else 0.0,
        identifiers_extracted=identifiers,
    )


async def prescreening_analyze_simple(pdf_bytes: bytes, filename: str) -> dict:
    """
    Simplified wrapper that returns a dict suitable for API responses.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        filename: Original filename
        
    Returns:
        Dict with prescreening result
    """
    result = await prescreening_analyze(pdf_bytes, filename)
    return result.model_dump()
