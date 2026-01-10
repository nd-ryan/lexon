"""Tests for the prescreening pipeline orchestrator."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.lib.pdf_prescreening.pipeline import prescreening_analyze
from app.lib.pdf_prescreening.models import (
    PrescreeningStatus,
    TextSource,
    TextExtractionResult,
    GeminiAnalysisResult,
    Identifiers,
    ResolutionResult,
    CourtListenerMetadata,
)


class TestPrescreeningAnalyze:
    """Tests for the main prescreening_analyze function."""

    @pytest.mark.asyncio
    async def test_good_text_layer_returns_immediately(self):
        """Should return text_layer_ok when Gemini says not flattened and extraction succeeds."""
        # Gemini says PDF is NOT flattened
        mock_gemini = GeminiAnalysisResult(
            is_flattened=False,
            confidence=0.95,
            identifiers=Identifiers(case_name="Smith v. Jones"),
        )
        
        # iLovePDF extraction succeeds with good quality
        mock_extraction = TextExtractionResult(
            text="This is good quality legal text. " * 100,
            per_page_texts=["Page 1 content " * 50, "Page 2 content " * 50],
            quality_score=0.9,
            is_usable=True,
            reasons=["Text quality is good"],
            total_chars=3000,
            page_count=2,
        )

        with patch(
            'app.lib.pdf_prescreening.pipeline.is_ilovepdf_configured',
            return_value=True
        ):
            with patch(
                'app.lib.pdf_prescreening.pipeline.ILovePdfClient'
            ) as MockILovePdf:
                mock_client = MagicMock()
                mock_client.extract_text.return_value = mock_extraction
                MockILovePdf.return_value = mock_client
                
                with patch(
                    'app.lib.pdf_prescreening.pipeline.analyze_pdf_images',
                    new_callable=AsyncMock,
                    return_value=mock_gemini
                ):
                    result = await prescreening_analyze(b"fake pdf bytes", "test.pdf")

        assert result.status == PrescreeningStatus.TEXT_LAYER_OK
        assert result.text_source == TextSource.PDF_TEXT
        assert result.confidence == 0.95  # Confidence now comes from Gemini
        assert result.error is None

    @pytest.mark.asyncio
    async def test_flattened_pdf_attempts_courtlistener(self):
        """Should attempt CourtListener resolution for flattened PDFs."""
        mock_extraction = TextExtractionResult(
            text="",
            per_page_texts=[""],
            quality_score=0.1,
            is_usable=False,
            reasons=["Very low character count"],
            total_chars=0,
            page_count=5,
        )

        mock_gemini = GeminiAnalysisResult(
            is_flattened=True,
            confidence=0.95,
            identifiers=Identifiers(
                case_name="Smith v. Jones",
                citations=["123 F.3d 456"],
            ),
        )

        mock_resolution = ResolutionResult(
            success=True,
            metadata=CourtListenerMetadata(
                opinion_id=12345,
                cluster_id=67890,
                case_name="Smith v. Jones",
                canonical_url="https://courtlistener.com/opinion/12345/",
                resolver_confidence=0.85,
            ),
            text="The court finds that...",
            candidates_checked=3,
        )

        with patch(
            'app.lib.pdf_prescreening.pipeline.is_ilovepdf_configured',
            return_value=True
        ):
            with patch(
                'app.lib.pdf_prescreening.pipeline.ILovePdfClient'
            ) as MockILovePdf:
                mock_ilovepdf = MagicMock()
                mock_ilovepdf.extract_text.return_value = mock_extraction
                MockILovePdf.return_value = mock_ilovepdf
                
                with patch(
                    'app.lib.pdf_prescreening.pipeline.analyze_pdf_images',
                    new_callable=AsyncMock,
                    return_value=mock_gemini
                ):
                    with patch(
                        'app.lib.pdf_prescreening.pipeline.CourtListenerClient'
                    ) as MockClient:
                        mock_client = MagicMock()
                        mock_client.resolve = AsyncMock(return_value=mock_resolution)
                        MockClient.return_value = mock_client

                        with patch(
                            'app.lib.pdf_prescreening.pipeline.extract_citations_from_text',
                            return_value=[]
                        ):
                            with patch(
                                'app.lib.pdf_prescreening.pipeline.extract_first_page_text',
                                return_value=""
                            ):
                                result = await prescreening_analyze(b"fake pdf", "test.pdf")

        assert result.status == PrescreeningStatus.COURTLISTENER_RESOLVED
        assert result.text_source == TextSource.COURTLISTENER
        assert result.courtlistener_metadata is not None
        assert result.courtlistener_metadata.opinion_id == 12345

    @pytest.mark.asyncio
    async def test_falls_back_to_ocr_when_courtlistener_fails(self):
        """Should fall back to iLovePDF OCR when CourtListener resolution fails."""
        mock_extraction = TextExtractionResult(
            text="",
            per_page_texts=[""],
            quality_score=0.1,
            is_usable=False,
            reasons=["Very low character count"],
            total_chars=0,
            page_count=5,
        )

        mock_gemini = GeminiAnalysisResult(
            is_flattened=True,
            confidence=0.95,
            identifiers=Identifiers(
                case_name="Unknown Case",
            ),
        )

        mock_failed_resolution = ResolutionResult(
            success=False,
            failure_reason="No confident match found",
            candidates_checked=3,
        )

        # OCR text needs to be > 500 chars to be considered successful
        mock_ocr_text = "This is OCR extracted text from the document. " * 20

        with patch(
            'app.lib.pdf_prescreening.pipeline.is_ilovepdf_configured',
            return_value=True
        ):
            with patch(
                'app.lib.pdf_prescreening.pipeline.ILovePdfClient'
            ) as MockILovePdf:
                mock_ilovepdf = MagicMock()
                mock_ilovepdf.extract_text.return_value = mock_extraction
                mock_ilovepdf.ocr_pdf.return_value = mock_ocr_text
                MockILovePdf.return_value = mock_ilovepdf
                
                with patch(
                    'app.lib.pdf_prescreening.pipeline.analyze_pdf_images',
                    new_callable=AsyncMock,
                    return_value=mock_gemini
                ):
                    with patch(
                        'app.lib.pdf_prescreening.pipeline.CourtListenerClient'
                    ) as MockClient:
                        mock_client = MagicMock()
                        mock_client.resolve = AsyncMock(return_value=mock_failed_resolution)
                        MockClient.return_value = mock_client

                        with patch(
                            'app.lib.pdf_prescreening.pipeline.extract_citations_from_text',
                            return_value=[]
                        ):
                            with patch(
                                'app.lib.pdf_prescreening.pipeline.extract_first_page_text',
                                return_value=""
                            ):
                                result = await prescreening_analyze(b"fake pdf", "test.pdf")

        assert result.status == PrescreeningStatus.OCR_RESOLVED
        assert result.text_source == TextSource.OCR
        assert result.text == mock_ocr_text

    @pytest.mark.asyncio
    async def test_fails_when_all_methods_fail(self):
        """Should return failed status when all extraction methods fail."""
        mock_extraction = TextExtractionResult(
            text="",
            per_page_texts=[""],
            quality_score=0.0,
            is_usable=False,
            reasons=["Empty document"],
            total_chars=0,
            page_count=0,
        )

        mock_gemini = GeminiAnalysisResult(
            is_flattened=True,
            confidence=0.5,
            identifiers=Identifiers(),  # No identifiers
        )

        with patch(
            'app.lib.pdf_prescreening.pipeline.is_ilovepdf_configured',
            return_value=True
        ):
            with patch(
                'app.lib.pdf_prescreening.pipeline.ILovePdfClient'
            ) as MockILovePdf:
                mock_ilovepdf = MagicMock()
                mock_ilovepdf.extract_text.return_value = mock_extraction
                mock_ilovepdf.ocr_pdf.return_value = ""  # OCR also fails
                MockILovePdf.return_value = mock_ilovepdf
                
                with patch(
                    'app.lib.pdf_prescreening.pipeline.analyze_pdf_images',
                    new_callable=AsyncMock,
                    return_value=mock_gemini
                ):
                    with patch(
                        'app.lib.pdf_prescreening.pipeline.extract_citations_from_text',
                        return_value=[]
                    ):
                        with patch(
                            'app.lib.pdf_prescreening.pipeline.extract_first_page_text',
                            return_value=""
                        ):
                            result = await prescreening_analyze(b"fake pdf", "test.pdf")

        assert result.status == PrescreeningStatus.FAILED
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_skip_courtlistener_flag(self):
        """Should skip CourtListener when flag is set."""
        mock_extraction = TextExtractionResult(
            text="",
            per_page_texts=[""],
            quality_score=0.1,
            is_usable=False,
            reasons=["Very low character count"],
            total_chars=0,
            page_count=5,
        )

        mock_gemini = GeminiAnalysisResult(
            is_flattened=True,
            confidence=0.95,
            identifiers=Identifiers(
                case_name="Smith v. Jones",
                citations=["123 F.3d 456"],
            ),
        )

        # OCR text needs to be > 500 chars to be considered successful
        mock_ocr_text = "OCR extracted text from the legal document. " * 20

        with patch(
            'app.lib.pdf_prescreening.pipeline.is_ilovepdf_configured',
            return_value=True
        ):
            with patch(
                'app.lib.pdf_prescreening.pipeline.ILovePdfClient'
            ) as MockILovePdf:
                mock_ilovepdf = MagicMock()
                mock_ilovepdf.extract_text.return_value = mock_extraction
                mock_ilovepdf.ocr_pdf.return_value = mock_ocr_text
                MockILovePdf.return_value = mock_ilovepdf
                
                with patch(
                    'app.lib.pdf_prescreening.pipeline.analyze_pdf_images',
                    new_callable=AsyncMock,
                    return_value=mock_gemini
                ):
                    with patch(
                        'app.lib.pdf_prescreening.pipeline.extract_citations_from_text',
                        return_value=[]
                    ):
                        with patch(
                            'app.lib.pdf_prescreening.pipeline.extract_first_page_text',
                            return_value=""
                        ):
                            result = await prescreening_analyze(
                                b"fake pdf", 
                                "test.pdf",
                                skip_courtlistener=True
                            )

        # Should go straight to OCR
        assert result.status == PrescreeningStatus.OCR_RESOLVED
        assert result.text_source == TextSource.OCR

    @pytest.mark.asyncio
    async def test_fails_when_ilovepdf_not_configured(self):
        """Should fail with clear error when iLovePDF is not configured."""
        with patch(
            'app.lib.pdf_prescreening.pipeline.is_ilovepdf_configured',
            return_value=False
        ):
            result = await prescreening_analyze(b"fake pdf", "test.pdf")

        assert result.status == PrescreeningStatus.FAILED
        assert "iLovePDF" in result.error


class TestIdentifiersSufficientData:
    """Tests for the Identifiers.has_sufficient_data method."""

    def test_citation_is_sufficient(self):
        """Having a citation alone should be sufficient."""
        ids = Identifiers(citations=["123 F.3d 456"])
        assert ids.has_sufficient_data() is True

    def test_case_name_plus_court_is_sufficient(self):
        """Case name plus court should be sufficient."""
        ids = Identifiers(case_name="Smith v. Jones", court="9th Cir")
        assert ids.has_sufficient_data() is True

    def test_case_name_plus_date_is_sufficient(self):
        """Case name plus date should be sufficient."""
        ids = Identifiers(case_name="Smith v. Jones", date="2023-05-15")
        assert ids.has_sufficient_data() is True

    def test_docket_plus_court_is_sufficient(self):
        """Docket number plus court should be sufficient."""
        ids = Identifiers(docket_number="22-1234", court="9th Cir")
        assert ids.has_sufficient_data() is True

    def test_case_name_alone_is_not_sufficient(self):
        """Case name alone should not be sufficient."""
        ids = Identifiers(case_name="Smith v. Jones")
        assert ids.has_sufficient_data() is False

    def test_empty_is_not_sufficient(self):
        """Empty identifiers should not be sufficient."""
        ids = Identifiers()
        assert ids.has_sufficient_data() is False
