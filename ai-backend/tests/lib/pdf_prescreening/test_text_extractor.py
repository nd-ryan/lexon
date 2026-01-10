"""Tests for PDF text extraction and quality assessment."""

import pytest
from app.lib.pdf_prescreening.text_extractor import (
    extract_text_with_quality,
    _assess_quality,
    _detect_junk_patterns,
    extract_first_page_text,
)


class TestAssessQuality:
    """Tests for the _assess_quality function."""

    def test_good_quality_text(self):
        """Text with good quality should be marked as usable."""
        # Simulate 3 pages of good legal text
        text = "This is a legal opinion. " * 100  # ~2500 chars
        per_page_texts = [
            "Page 1 content with sufficient text. " * 10,  # ~370 chars
            "Page 2 content with more legal analysis. " * 10,
            "Page 3 content with conclusion. " * 10,
        ]
        
        score, is_usable, reasons = _assess_quality(text, per_page_texts, 3)
        
        assert is_usable is True
        assert score >= 0.7
        assert "Text quality is good" in reasons

    def test_low_character_count(self):
        """Text with very few characters should be marked as not usable."""
        text = "Short text"
        per_page_texts = ["Short text"]
        
        score, is_usable, reasons = _assess_quality(text, per_page_texts, 1)
        
        assert is_usable is False
        assert any("character count" in r.lower() for r in reasons)

    def test_few_pages_with_content(self):
        """Document where most pages have no text should flag a warning."""
        text = "Some text on page 1"
        per_page_texts = [
            "Some text on page 1. " * 20,  # ~400 chars
            "",  # Empty page
            "",  # Empty page
            "",  # Empty page
        ]
        
        score, is_usable, reasons = _assess_quality(text, per_page_texts, 4)
        
        # Should have low score due to few pages with content
        assert any("pages" in r.lower() for r in reasons)

    def test_non_printable_characters(self):
        """Text with many non-printable characters should be flagged."""
        # Create text with non-printable characters
        text = "Normal text" + "\x00\x01\x02\x03\x04" * 50
        per_page_texts = [text]
        
        score, is_usable, reasons = _assess_quality(text, per_page_texts, 1)
        
        assert any("printable" in r.lower() for r in reasons)

    def test_low_alpha_ratio(self):
        """Text with very few alphabetic characters should be flagged."""
        # Create text with low alpha ratio (mostly numbers/symbols)
        text = "123 456 789 !@# $%^ &*( )_+ " * 100
        per_page_texts = [text]
        
        score, is_usable, reasons = _assess_quality(text, per_page_texts, 1)
        
        # Should flag low/very low alpha ratio
        assert any("alpha" in r.lower() for r in reasons)
        # Should not be usable due to low alpha ratio
        assert is_usable is False

    def test_empty_text(self):
        """Empty text should not be usable."""
        score, is_usable, reasons = _assess_quality("", [], 0)
        
        assert is_usable is False
        # Score may be small non-zero due to weighted averaging, but should be very low
        assert score < 0.2


class TestDetectJunkPatterns:
    """Tests for junk pattern detection."""

    def test_pdf_header_pattern(self):
        """Should detect PDF header in text."""
        text = "%PDF-1.4 some text after"
        assert _detect_junk_patterns(text) is True

    def test_pdf_stream_pattern(self):
        """Should detect PDF stream objects."""
        text = "stream\n<binary data>\nendstream"
        assert _detect_junk_patterns(text) is True

    def test_clean_text(self):
        """Clean legal text should not trigger junk detection."""
        text = """
        UNITED STATES COURT OF APPEALS
        FOR THE NINTH CIRCUIT
        
        JOHN DOE, Plaintiff-Appellant,
        v.
        JANE ROE, Defendant-Appellee.
        
        No. 22-1234
        
        This appeal arises from the district court's grant of summary judgment.
        """
        assert _detect_junk_patterns(text) is False


class TestExtractTextWithQuality:
    """Tests for the main extraction function."""

    def test_invalid_pdf_bytes(self):
        """Should handle invalid PDF bytes gracefully."""
        result = extract_text_with_quality(b"not a pdf")
        
        assert result.is_usable is False
        assert result.total_chars == 0
        assert len(result.reasons) > 0

    def test_empty_bytes(self):
        """Should handle empty bytes."""
        result = extract_text_with_quality(b"")
        
        assert result.is_usable is False


class TestExtractFirstPageText:
    """Tests for first page extraction."""

    def test_invalid_pdf(self):
        """Should return None for invalid PDF."""
        result = extract_first_page_text(b"not a pdf")
        assert result is None

    def test_empty_bytes(self):
        """Should return None for empty bytes."""
        result = extract_first_page_text(b"")
        assert result is None
