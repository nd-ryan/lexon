"""PDF Pre-screening module for detecting and resolving flattened PDFs."""

import logging
from app.lib.logging_config import setup_logger

# Initialize a shared logger for the entire prescreening module
# This logger is configured with proper handlers for console and file output
_logger = setup_logger("prescreening")


def get_logger() -> logging.Logger:
    """Get the shared prescreening logger."""
    return _logger


from .models import (
    PrescreeningStatus,
    TextSource,
    TextExtractionResult,
    Identifiers,
    GeminiAnalysisResult,
    OpinionCandidate,
    CourtListenerMetadata,
    ResolutionResult,
    PrescreeningResult,
)
from .pipeline import prescreening_analyze
from .ilovepdf_client import ILovePdfClient, is_ilovepdf_configured

__all__ = [
    "PrescreeningStatus",
    "TextSource",
    "TextExtractionResult",
    "Identifiers",
    "GeminiAnalysisResult",
    "OpinionCandidate",
    "CourtListenerMetadata",
    "ResolutionResult",
    "PrescreeningResult",
    "prescreening_analyze",
    "ILovePdfClient",
    "is_ilovepdf_configured",
    "get_logger",
]
