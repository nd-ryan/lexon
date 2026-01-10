"""Pydantic models for PDF pre-screening pipeline."""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class PrescreeningStatus(str, Enum):
    """Status of the pre-screening result."""
    TEXT_LAYER_OK = "text_layer_ok"
    COURTLISTENER_RESOLVED = "courtlistener_resolved"
    OCR_RESOLVED = "ocr_resolved"
    FAILED = "failed"


class TextSource(str, Enum):
    """Source of the extracted text."""
    PDF_TEXT = "pdf_text"
    COURTLISTENER = "courtlistener"
    OCR = "ocr"


class TextExtractionResult(BaseModel):
    """Result of text extraction from PDF via pdfplumber."""
    text: str = Field(description="Full extracted text from PDF")
    per_page_texts: list[str] = Field(description="Text extracted from each page")
    quality_score: float = Field(ge=0.0, le=1.0, description="Quality score 0-1")
    is_usable: bool = Field(description="Whether the text quality is sufficient")
    reasons: list[str] = Field(default_factory=list, description="Reasons for quality assessment")
    total_chars: int = Field(description="Total character count")
    page_count: int = Field(description="Number of pages in PDF")


class Identifiers(BaseModel):
    """Legal document identifiers extracted from PDF."""
    case_name: Optional[str] = Field(default=None, description="Case name (e.g., 'Smith v. Jones')")
    court: Optional[str] = Field(default=None, description="Court name")
    date: Optional[str] = Field(default=None, description="Decision date (YYYY-MM-DD if possible)")
    docket_number: Optional[str] = Field(default=None, description="Docket number")
    citations: list[str] = Field(default_factory=list, description="Legal citations found")
    
    def has_sufficient_data(self) -> bool:
        """Check if we have enough data to attempt CourtListener resolution."""
        # Need at least a citation, or case_name + one other identifier
        if self.citations:
            return True
        if self.case_name and (self.court or self.date or self.docket_number):
            return True
        if self.docket_number and self.court:
            return True
        return False


class GeminiAnalysisResult(BaseModel):
    """Result of Gemini vision analysis of PDF pages."""
    is_flattened: bool = Field(description="Whether PDF appears to be scanned/image-only")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the assessment")
    identifiers: Identifiers = Field(description="Extracted legal document identifiers")
    raw_response: Optional[str] = Field(default=None, description="Raw Gemini response for debugging")


class OpinionCandidate(BaseModel):
    """A candidate opinion from CourtListener search."""
    opinion_id: int = Field(description="CourtListener opinion ID")
    cluster_id: int = Field(description="CourtListener cluster ID")
    case_name: str = Field(description="Case name from CourtListener")
    court: Optional[str] = Field(default=None, description="Court identifier")
    date_filed: Optional[str] = Field(default=None, description="Date filed")
    docket_number: Optional[str] = Field(default=None, description="Docket number")
    citation: Optional[str] = Field(default=None, description="Primary citation")
    absolute_url: Optional[str] = Field(default=None, description="URL path on CourtListener")
    score: float = Field(default=0.0, description="Match score computed during resolution")


class CourtListenerMetadata(BaseModel):
    """Metadata from a resolved CourtListener opinion."""
    opinion_id: int = Field(description="CourtListener opinion ID")
    cluster_id: int = Field(description="CourtListener cluster ID")
    case_name: str = Field(description="Case name")
    court: Optional[str] = Field(default=None, description="Court")
    date_filed: Optional[str] = Field(default=None, description="Date filed")
    docket_number: Optional[str] = Field(default=None, description="Docket number")
    citation: Optional[str] = Field(default=None, description="Primary citation")
    canonical_url: str = Field(description="Full URL to opinion on CourtListener")
    resolver_confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the match")


class ResolutionResult(BaseModel):
    """Result of CourtListener resolution attempt."""
    success: bool = Field(description="Whether resolution was successful")
    metadata: Optional[CourtListenerMetadata] = Field(default=None, description="Opinion metadata if resolved")
    text: Optional[str] = Field(default=None, description="Opinion plain text if resolved")
    candidates_checked: int = Field(default=0, description="Number of candidates evaluated")
    top_candidates: list[OpinionCandidate] = Field(default_factory=list, description="Top candidates for debugging")
    failure_reason: Optional[str] = Field(default=None, description="Why resolution failed")


class PrescreeningResult(BaseModel):
    """Final result of the pre-screening pipeline."""
    status: PrescreeningStatus = Field(description="Overall status of pre-screening")
    text: Optional[str] = Field(default=None, description="Extracted/resolved text")
    text_source: Optional[TextSource] = Field(default=None, description="Source of the text")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Confidence in the result")
    courtlistener_metadata: Optional[CourtListenerMetadata] = Field(
        default=None, description="CourtListener metadata if resolved via CL"
    )
    warnings: list[str] = Field(default_factory=list, description="Warnings about the result")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    
    # Debugging/audit info
    text_quality_score: Optional[float] = Field(default=None, description="Initial text quality score")
    identifiers_extracted: Optional[Identifiers] = Field(default=None, description="Identifiers extracted from PDF")
