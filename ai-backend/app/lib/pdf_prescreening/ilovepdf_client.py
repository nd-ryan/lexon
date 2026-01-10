"""iLovePDF API client for text extraction and OCR."""

import os
import io
import tempfile
import logging
from typing import Optional
from pathlib import Path

import pdfplumber
from iloveapi import ILoveApi
from httpx import Timeout

from .models import TextExtractionResult

# Use the shared prescreening logger (configured in __init__.py)
logger = logging.getLogger("prescreening")

# Configuration
ILOVEPDF_PUBLIC_KEY = os.getenv("ILOVEPDF_PUBLIC_KEY", "")
ILOVEPDF_SECRET_KEY = os.getenv("ILOVEPDF_SECRET_KEY", "")

# Timeout configuration - OCR can take a long time for large documents
# Default httpx timeout is 10s which is too short for OCR
ILOVEPDF_TIMEOUT = float(os.getenv("ILOVEPDF_TIMEOUT", "300.0"))  # 5 minutes default
MAX_PAGES_FOR_EXTRACT = int(os.getenv("PRESCREENING_MAX_EXTRACT_PAGES", "4"))

# Quality assessment thresholds (same as text_extractor.py)
MIN_TOTAL_CHARS = int(os.getenv("PRESCREENING_MIN_CHARS", "1500"))
MIN_PAGE_CHARS = int(os.getenv("PRESCREENING_MIN_PAGE_CHARS", "150"))
MIN_PAGE_RATIO = float(os.getenv("PRESCREENING_MIN_PAGE_RATIO", "0.5"))
MIN_PRINTABLE_RATIO = float(os.getenv("PRESCREENING_MIN_PRINTABLE_RATIO", "0.95"))
MIN_ALPHA_RATIO = float(os.getenv("PRESCREENING_MIN_ALPHA_RATIO", "0.50"))


class ILovePdfClient:
    """
    Client for iLovePDF API operations.
    
    Provides text extraction and OCR capabilities using iLovePDF cloud services:
    - extract_text(): Uses the "extract" task to get embedded text from PDFs
    - ocr_pdf(): Uses the "pdfocr" task to OCR scanned/flattened PDFs
    """
    
    def __init__(
        self, 
        public_key: Optional[str] = None, 
        secret_key: Optional[str] = None
    ):
        self.public_key = public_key or ILOVEPDF_PUBLIC_KEY
        self.secret_key = secret_key or ILOVEPDF_SECRET_KEY
        
        if not self.public_key or not self.secret_key:
            raise ValueError(
                "iLovePDF API keys not configured. "
                "Set ILOVEPDF_PUBLIC_KEY and ILOVEPDF_SECRET_KEY environment variables."
            )
        
        self._client: Optional[ILoveApi] = None
    
    def _get_client(self) -> ILoveApi:
        """Get or create the iLovePDF client."""
        if self._client is None:
            # Use a generous timeout for OCR operations which can take several minutes
            # for large documents. Default httpx timeout of 10s is too short.
            timeout = Timeout(timeout=ILOVEPDF_TIMEOUT)
            self._client = ILoveApi(
                public_key=self.public_key,
                secret_key=self.secret_key,
                timeout=timeout,
            )
        return self._client
    
    def extract_text(
        self, 
        pdf_bytes: bytes, 
        max_pages: Optional[int] = None
    ) -> TextExtractionResult:
        """
        Extract text from PDF using iLovePDF extract task.
        
        The iLovePDF "extract" task extracts embedded text from PDFs and returns
        it as a .txt file. This is different from OCR - it only works for PDFs
        that have an actual text layer (not flattened/scanned PDFs).
        
        For prescreening, we only extract from the first few pages to assess quality.
        
        Args:
            pdf_bytes: Raw PDF file bytes
            max_pages: Maximum pages to extract (default: MAX_PAGES_FOR_EXTRACT)
            
        Returns:
            TextExtractionResult with extracted text and quality metrics
        """
        if max_pages is None:
            max_pages = MAX_PAGES_FOR_EXTRACT
        
        page_count = self._count_pages(pdf_bytes)
        
        try:
            logger.info("Starting iLovePDF extract task...")
            
            # Write PDF to temp file for upload
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
                tmp_pdf.write(pdf_bytes)
                tmp_pdf_path = tmp_pdf.name
            
            try:
                # Create extract task and process
                client = self._get_client()
                task = client.create_task("extract")
                
                # process_files handles upload, processing
                task.process_files(tmp_pdf_path)
                
                # download() without args returns the file bytes directly
                # For extract task, this is the .txt file content
                txt_bytes = task.download()
                
                if txt_bytes is None or len(txt_bytes) == 0:
                    logger.warning("iLovePDF extract returned empty content")
                    full_text = ""
                else:
                    # Decode the text file content
                    full_text = txt_bytes.decode("utf-8", errors="replace").strip()
                    logger.info(f"iLovePDF extract successful: {len(full_text)} chars")
                
            finally:
                # Clean up temp PDF file
                os.unlink(tmp_pdf_path)
            
            total_chars = len(full_text)
            
            # Split into per-page texts for quality assessment
            per_page_texts = self._split_by_pages(full_text, page_count)
            
            # Limit to max_pages for assessment
            per_page_texts = per_page_texts[:max_pages]
            
            logger.info(
                f"iLovePDF extraction: {page_count} pages total, "
                f"got {len(per_page_texts)} text chunks ({total_chars} chars)"
            )
            
            # Log text preview
            if full_text:
                preview = full_text[:500].replace('\n', '\\n')
                logger.info(f"Text preview (first 500 chars): {preview}")
            
            # Assess quality
            quality_score, is_usable, reasons = self._assess_quality(
                full_text, per_page_texts, len(per_page_texts) or page_count
            )
            
            return TextExtractionResult(
                text=full_text,
                per_page_texts=per_page_texts,
                quality_score=quality_score,
                is_usable=is_usable,
                reasons=reasons,
                total_chars=total_chars,
                page_count=page_count,
            )
            
        except Exception as e:
            logger.error(f"iLovePDF text extraction failed: {e}", exc_info=True)
            return self._create_failed_result(page_count, str(e))
    
    def ocr_pdf(self, pdf_bytes: bytes) -> Optional[str]:
        """
        Perform OCR on a PDF using iLovePDF OCR task.
        
        The OCR task converts scanned/image PDFs into searchable PDFs,
        then we extract the text from the resulting PDF.
        
        Args:
            pdf_bytes: Raw PDF file bytes
            
        Returns:
            Extracted text from OCR, or None if failed
        """
        try:
            # Write PDF to temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
                tmp_pdf.write(pdf_bytes)
                tmp_pdf_path = tmp_pdf.name
            
            try:
                # Create OCR task and process
                client = self._get_client()
                task = client.create_task("pdfocr")
                
                logger.info("Starting iLovePDF OCR task...")
                
                # Download result to temp directory
                with tempfile.TemporaryDirectory() as tmp_dir:
                    output_path = Path(tmp_dir) / "output.pdf"
                    
                    # process_files handles upload, processing, and download
                    task.process_files(tmp_pdf_path)
                    task.download(str(output_path))
                    
                    # Find the processed PDF
                    pdf_files = []
                    if output_path.is_file() and output_path.suffix == '.pdf':
                        pdf_files = [output_path]
                    elif output_path.is_file() and output_path.suffix == '.zip':
                        # Extract zip and find pdf files
                        import zipfile
                        with zipfile.ZipFile(output_path, 'r') as zip_ref:
                            zip_ref.extractall(tmp_dir)
                        pdf_files = list(Path(tmp_dir).glob("**/*.pdf"))
                    else:
                        pdf_files = list(Path(tmp_dir).glob("**/*.pdf"))
                    
                    if not pdf_files:
                        logger.error("iLovePDF OCR returned no PDF file")
                        return None
                    
                    # Extract text from the OCR'd PDF using pdfplumber
                    text = self._extract_text_from_pdf(pdf_files[0])
                
                if text:
                    logger.info(f"iLovePDF OCR successful: {len(text)} chars extracted")
                else:
                    logger.warning("iLovePDF OCR produced empty text")
                
                return text
                
            finally:
                # Clean up temp PDF file
                os.unlink(tmp_pdf_path)
            
        except Exception as e:
            logger.error(f"iLovePDF OCR failed: {e}", exc_info=True)
            return None
    
    def _count_pages(self, pdf_bytes: bytes) -> int:
        """Count pages in a PDF using pdfplumber."""
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                return len(pdf.pages)
        except Exception as e:
            logger.warning(f"Failed to count pages: {e}")
            return 0
    
    def _extract_text_from_pdf(self, pdf_path: Path) -> Optional[str]:
        """Extract text from a PDF file using pdfplumber."""
        try:
            texts = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    texts.append(text)
            return "\n\n".join(texts).strip()
        except Exception as e:
            logger.error(f"Failed to extract text from OCR'd PDF: {e}")
            return None
    
    def _split_by_pages(self, text: str, expected_pages: int) -> list[str]:
        """
        Split extracted text into per-page chunks.
        
        iLovePDF extract typically uses form feed characters or multiple
        newlines to separate pages. This is a best-effort heuristic.
        """
        # Try form feed first (common page separator)
        if '\f' in text:
            pages = text.split('\f')
            return [p.strip() for p in pages if p.strip()]
        
        # Fall back to multiple newlines as page separator
        if '\n\n\n' in text:
            pages = text.split('\n\n\n')
            pages = [p.strip() for p in pages if p.strip()]
            return pages if pages else [text]
        
        # No clear page separation, return as single chunk
        return [text] if text.strip() else []
    
    def _assess_quality(
        self, 
        full_text: str, 
        per_page_texts: list[str], 
        page_count: int
    ) -> tuple[float, bool, list[str]]:
        """
        Assess the quality of extracted text.
        
        Same logic as text_extractor._assess_quality for consistency.
        """
        reasons: list[str] = []
        scores: list[float] = []
        
        total_chars = len(full_text)
        
        # Check 1: Minimum total characters
        char_score = 0.0
        if total_chars >= MIN_TOTAL_CHARS:
            char_score = 1.0
        elif total_chars >= MIN_TOTAL_CHARS * 0.5:
            char_score = 0.5
            reasons.append(f"Low character count: {total_chars}")
        else:
            char_score = 0.0
            reasons.append(f"Very low character count: {total_chars}")
        scores.append(char_score)
        
        # Check 2: Per-page character distribution
        page_score = 0.0
        pages_with_content = 0
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
        scores.append(page_score)
        
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
                reasons.append(f"Some non-printable characters: {printable_ratio:.1%}")
            else:
                printable_score = 0.0
                reasons.append(f"Too many non-printable characters: {printable_ratio:.1%}")
        scores.append(printable_score)
        
        # Check 4: Alphabetic character ratio
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
        
        # Check 5: Junk pattern detection (cid: patterns, etc.)
        junk_score = 1.0
        if "(cid:" in full_text.lower():
            junk_score = 0.0
            reasons.append("Detected (cid:X) patterns in text")
        scores.append(junk_score)
        
        # Calculate overall score (weighted average)
        weights = [0.25, 0.25, 0.2, 0.2, 0.1]
        quality_score = sum(s * w for s, w in zip(scores, weights))
        
        # Determine usability
        is_usable = (
            quality_score >= 0.7 
            and scores[0] >= 0.5  # char count
            and scores[1] >= 0.5  # page distribution
            and scores[3] >= 0.5  # alpha ratio
            and scores[4] >= 0.5  # no junk
        )
        
        if is_usable and not reasons:
            reasons.append("Text quality is good")
        
        # Log quality assessment
        logger.info(
            f"Text quality assessment: total_chars={total_chars}, "
            f"pages_with_content={pages_with_content}/{page_count}, "
            f"printable_ratio={printable_ratio:.1%}, "
            f"alpha_ratio={alpha_ratio:.1%}"
        )
        logger.info(
            f"Quality scores: char={char_score:.1f}, page={page_score:.1f}, "
            f"printable={printable_score:.1f}, alpha={alpha_score:.1f}, junk={junk_score:.1f} "
            f"-> weighted={quality_score:.2f}, usable={is_usable}"
        )
        if reasons:
            logger.info(f"Quality issues: {'; '.join(reasons)}")
        
        return quality_score, is_usable, reasons
    
    def _create_failed_result(self, page_count: int, error: str) -> TextExtractionResult:
        """Create a failed extraction result."""
        return TextExtractionResult(
            text="",
            per_page_texts=[],
            quality_score=0.0,
            is_usable=False,
            reasons=[f"Extraction failed: {error}"],
            total_chars=0,
            page_count=page_count,
        )


def is_ilovepdf_configured() -> bool:
    """Check if iLovePDF API keys are configured."""
    return bool(ILOVEPDF_PUBLIC_KEY and ILOVEPDF_SECRET_KEY)
