"""Text extraction and quality assessment for PDFs using pdfplumber."""

import os
import re
import logging
from io import BytesIO
from typing import Optional

import pdfplumber

from .models import TextExtractionResult

# Use the shared prescreening logger (configured in __init__.py)
logger = logging.getLogger("prescreening")

# Configuration (can be overridden via environment variables)
MIN_TOTAL_CHARS = int(os.getenv("PRESCREENING_MIN_CHARS", "1500"))
MIN_PAGE_CHARS = int(os.getenv("PRESCREENING_MIN_PAGE_CHARS", "150"))
MIN_PAGE_RATIO = float(os.getenv("PRESCREENING_MIN_PAGE_RATIO", "0.5"))
MIN_PRINTABLE_RATIO = float(os.getenv("PRESCREENING_MIN_PRINTABLE_RATIO", "0.95"))
# Alpha ratio threshold - legal docs are text-heavy, so we expect >= 50%
MIN_ALPHA_RATIO = float(os.getenv("PRESCREENING_MIN_ALPHA_RATIO", "0.50"))
# Number of pages to extract for quality assessment (prescreening only)
MAX_PAGES_FOR_QUALITY_CHECK = int(os.getenv("PRESCREENING_MAX_EXTRACT_PAGES", "4"))

# Junk patterns that indicate binary/corrupt text
JUNK_PATTERNS = [
    r"%PDF-\d+\.\d+",  # PDF header in text
    r"stream\s*\n.*?endstream",  # PDF stream objects
    r"obj\s*\n.*?endobj",  # PDF objects
    r"[\x00-\x08\x0b\x0c\x0e-\x1f]{5,}",  # Non-printable sequences
    r"(?:[\ufffd\ufffe\uffff]){3,}",  # Unicode replacement chars
]


def extract_text_with_quality(pdf_bytes: bytes, max_pages: Optional[int] = None) -> TextExtractionResult:
    """
    Extract text from PDF using pdfplumber and assess quality.
    
    For prescreening, we only extract the first few pages to speed up the process.
    Quality assessment is based on the sampled pages.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        max_pages: Maximum pages to extract (None = all pages, default uses MAX_PAGES_FOR_QUALITY_CHECK)
        
    Returns:
        TextExtractionResult with text, quality metrics, and usability assessment
    """
    per_page_texts: list[str] = []
    reasons: list[str] = []
    
    # Default to configured max for prescreening
    if max_pages is None:
        max_pages = MAX_PAGES_FOR_QUALITY_CHECK
    
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
            pages_to_extract = min(max_pages, page_count) if max_pages > 0 else page_count
            
            for i, page in enumerate(pdf.pages):
                if i >= pages_to_extract:
                    break
                try:
                    page_text = page.extract_text() or ""
                    per_page_texts.append(page_text)
                except Exception as e:
                    logger.warning(f"Failed to extract text from page {page.page_number}: {e}")
                    per_page_texts.append("")
                    
    except Exception as e:
        logger.error(f"Failed to open PDF: {e}")
        return TextExtractionResult(
            text="",
            per_page_texts=[],
            quality_score=0.0,
            is_usable=False,
            reasons=[f"Failed to open PDF: {str(e)}"],
            total_chars=0,
            page_count=0,
        )
    
    # Combine extracted page texts
    full_text = "\n\n".join(per_page_texts).strip()
    total_chars = len(full_text)
    
    # Log extraction summary (note: page_count is total, but we only extracted some)
    extracted_pages = len(per_page_texts)
    logger.info(f"PDF extraction: {extracted_pages}/{page_count} pages extracted, {total_chars} chars")
    
    # Log per-page char counts to help diagnose issues
    page_char_counts = [len(t) for t in per_page_texts]
    logger.info(f"Per-page char counts: {page_char_counts}")
    
    # Log text preview (first 500 chars) to see what was actually extracted
    if full_text:
        preview = full_text[:500].replace('\n', '\\n')
        logger.info(f"Text preview (first 500 chars): {preview}")
    else:
        logger.info("Text preview: <empty>")
    
    # Calculate quality metrics based on extracted pages (not total)
    # We assess quality on the sample - if first N pages are good, assume rest are too
    quality_score, is_usable, reasons = _assess_quality(
        full_text, per_page_texts, extracted_pages
    )
    
    return TextExtractionResult(
        text=full_text,
        per_page_texts=per_page_texts,
        quality_score=quality_score,
        is_usable=is_usable,
        reasons=reasons,
        total_chars=total_chars,
        page_count=page_count,  # Store total page count for reference
    )


def _assess_quality(
    full_text: str, 
    per_page_texts: list[str], 
    page_count: int
) -> tuple[float, bool, list[str]]:
    """
    Assess the quality of extracted text.
    
    Returns:
        Tuple of (quality_score, is_usable, reasons)
    """
    reasons: list[str] = []
    scores: list[float] = []
    check_details: dict[str, dict] = {}  # For detailed logging
    
    total_chars = len(full_text)
    
    # Check 1: Minimum total characters
    char_score = 0.0
    if total_chars >= MIN_TOTAL_CHARS:
        char_score = 1.0
    elif total_chars >= MIN_TOTAL_CHARS * 0.5:
        char_score = 0.5
        reasons.append(f"Low character count: {total_chars} (expected >= {MIN_TOTAL_CHARS})")
    else:
        char_score = 0.0
        reasons.append(f"Very low character count: {total_chars} (expected >= {MIN_TOTAL_CHARS})")
    scores.append(char_score)
    check_details["total_chars"] = {
        "value": total_chars,
        "threshold": MIN_TOTAL_CHARS,
        "score": char_score,
    }
    
    # Check 2: Per-page character distribution
    page_score = 0.0
    pages_with_content = 0
    page_ratio = 0.0
    if page_count > 0:
        pages_with_content = sum(1 for t in per_page_texts if len(t) >= MIN_PAGE_CHARS)
        page_ratio = pages_with_content / page_count
        
        if page_ratio >= MIN_PAGE_RATIO:
            page_score = 1.0
        elif page_ratio >= MIN_PAGE_RATIO * 0.5:
            page_score = 0.5
            reasons.append(f"Only {pages_with_content}/{page_count} pages have sufficient text")
        else:
            page_score = 0.0
            reasons.append(f"Very few pages with text: {pages_with_content}/{page_count}")
    else:
        page_score = 0.0
        reasons.append("No pages found in PDF")
    scores.append(page_score)
    check_details["page_distribution"] = {
        "pages_with_content": pages_with_content,
        "total_pages": page_count,
        "ratio": page_ratio,
        "threshold": MIN_PAGE_RATIO,
        "score": page_score,
    }
    
    # Check 3: Printable character ratio
    printable_score = 0.0
    printable_ratio = 0.0
    if total_chars > 0:
        printable_chars = sum(1 for c in full_text if c.isprintable() or c in '\n\r\t')
        printable_ratio = printable_chars / total_chars
        
        if printable_ratio >= MIN_PRINTABLE_RATIO:
            printable_score = 1.0
        elif printable_ratio >= 0.8:
            printable_score = 0.5
            reasons.append(f"Some non-printable characters: {printable_ratio:.1%} printable")
        else:
            printable_score = 0.0
            reasons.append(f"Too many non-printable characters: {printable_ratio:.1%} printable")
    scores.append(printable_score)
    check_details["printable_ratio"] = {
        "ratio": printable_ratio,
        "threshold": MIN_PRINTABLE_RATIO,
        "score": printable_score,
    }
    
    # Check 4: Alphabetic character ratio
    # For legal documents, we expect high alpha ratio (lots of words)
    alpha_score = 0.0
    alpha_ratio = 0.0
    if total_chars > 0:
        alpha_chars = sum(1 for c in full_text if c.isalpha())
        alpha_ratio = alpha_chars / total_chars
        
        if alpha_ratio >= MIN_ALPHA_RATIO:
            alpha_score = 1.0
        elif alpha_ratio >= MIN_ALPHA_RATIO * 0.5:
            alpha_score = 0.5
            reasons.append(f"Low alphabetic ratio: {alpha_ratio:.1%}")
        else:
            alpha_score = 0.0
            reasons.append(f"Very low alphabetic ratio: {alpha_ratio:.1%}")
    scores.append(alpha_score)
    check_details["alpha_ratio"] = {
        "ratio": alpha_ratio,
        "threshold": MIN_ALPHA_RATIO,
        "score": alpha_score,
    }
    
    # Check 5: Junk pattern detection
    has_junk = _detect_junk_patterns(full_text)
    junk_score = 0.0 if has_junk else 1.0
    if has_junk:
        reasons.append("Detected PDF binary/junk patterns in text")
    scores.append(junk_score)
    check_details["junk_detection"] = {
        "has_junk": has_junk,
        "score": junk_score,
    }
    
    # Calculate overall score (weighted average)
    weights = [0.25, 0.25, 0.2, 0.2, 0.1]  # Total, pages, printable, alpha, junk
    quality_score = sum(s * w for s, w in zip(scores, weights))
    
    # Determine usability - stricter criteria for legal documents
    # Text is usable if:
    # - Overall score >= 0.7
    # - Has reasonable char count (score >= 0.5)
    # - No major junk (score >= 0.5)
    # - Alphabetic ratio is decent (score >= 0.5) - important for legal docs
    # - At least some pages have content (score >= 0.5)
    is_usable = (
        quality_score >= 0.7 
        and scores[0] >= 0.5  # char count
        and scores[1] >= 0.5  # page distribution
        and scores[3] >= 0.5  # alpha ratio - added check
        and scores[4] >= 0.5  # no junk
    )
    
    if is_usable and not reasons:
        reasons.append("Text quality is good")
    
    # Log detailed quality assessment
    logger.info(
        f"Text quality assessment: "
        f"total_chars={total_chars}, "
        f"pages_with_content={pages_with_content}/{page_count}, "
        f"printable_ratio={printable_ratio:.1%}, "
        f"alpha_ratio={alpha_ratio:.1%}, "
        f"has_junk={has_junk}"
    )
    logger.info(
        f"Quality scores: "
        f"char={char_score:.1f}, page={page_score:.1f}, "
        f"printable={printable_score:.1f}, alpha={alpha_score:.1f}, junk={junk_score:.1f} "
        f"-> weighted={quality_score:.2f}, usable={is_usable}"
    )
    if reasons:
        logger.info(f"Quality issues: {'; '.join(reasons)}")
    
    return quality_score, is_usable, reasons


def _detect_junk_patterns(text: str) -> bool:
    """Detect patterns indicating binary/corrupt text extraction."""
    for pattern in JUNK_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            return True
    return False


def extract_first_page_text(pdf_bytes: bytes) -> Optional[str]:
    """
    Extract text from just the first page of a PDF.
    Useful for quick identifier extraction even from poor quality PDFs.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        
    Returns:
        First page text, or None if extraction fails
    """
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            if pdf.pages:
                return pdf.pages[0].extract_text() or ""
    except Exception as e:
        logger.warning(f"Failed to extract first page text: {e}")
    return None
