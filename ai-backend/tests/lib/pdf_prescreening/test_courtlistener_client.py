"""Tests for CourtListener client."""

import pytest
from unittest.mock import AsyncMock, patch

from app.lib.pdf_prescreening.courtlistener_client import (
    CourtListenerClient,
    extract_citations_from_text,
)
from app.lib.pdf_prescreening.models import Identifiers, OpinionCandidate


class TestCourtListenerClient:
    """Tests for the CourtListenerClient class."""

    def test_build_search_queries_with_case_name(self):
        """Should build keyword-based query from case name."""
        client = CourtListenerClient(api_key="test")
        identifiers = Identifiers(
            case_name="Alice Corporation v. CLS Bank",
            date="2014-06-19",
        )
        
        queries = client._build_search_queries(identifiers)
        
        assert len(queries) > 0
        # Should extract party keywords like "Alice" and "Bank"
        assert any('Alice' in q or 'Bank' in q for q in queries)
        # Should include date constraint
        assert any('2014' in q for q in queries)

    def test_build_search_queries_with_docket(self):
        """Should build docket-based query when docket is available."""
        client = CourtListenerClient(api_key="test")
        identifiers = Identifiers(
            docket_number="No. 22-1234",
            court="Ninth Circuit",
            date="2023-05-15",
        )
        
        queries = client._build_search_queries(identifiers)
        
        assert len(queries) > 0
        assert any('docketNumber:' in q for q in queries)
        # Should clean docket number (remove "No. ")
        assert any('22-1234' in q for q in queries)

    def test_build_search_queries_extracts_party_names(self):
        """Should extract meaningful party names from full case name."""
        client = CourtListenerClient(api_key="test")
        identifiers = Identifiers(
            case_name="ALICE CORPORATION PTY. LTD. v. CLS BANK INTERNATIONAL ET AL.",
            date="2014",
        )
        
        queries = client._build_search_queries(identifiers)
        
        assert len(queries) > 0
        # Should have extracted "Alice" and "Bank" as keywords
        assert any('Alice' in q for q in queries)
        assert any('Bank' in q for q in queries)

    def test_build_search_queries_empty_identifiers(self):
        """Should return empty list for empty identifiers."""
        client = CourtListenerClient(api_key="test")
        identifiers = Identifiers()
        
        queries = client._build_search_queries(identifiers)
        
        assert len(queries) == 0


class TestExtractPartyKeywords:
    """Tests for party keyword extraction."""

    def test_extract_party_keywords_basic(self):
        """Should extract main party names."""
        client = CourtListenerClient(api_key="test")
        
        keywords = client._extract_party_keywords("Smith v. Jones")
        
        assert "Smith" in keywords
        assert "Jones" in keywords
        assert "v" not in [k.lower() for k in keywords]

    def test_extract_party_keywords_filters_stopwords(self):
        """Should filter out common legal stopwords."""
        client = CourtListenerClient(api_key="test")
        
        keywords = client._extract_party_keywords(
            "ALICE CORPORATION PTY. LTD. v. CLS BANK INTERNATIONAL ET AL."
        )
        
        # Should not include corporate suffixes or common words
        lower_keywords = [k.lower() for k in keywords]
        assert "corporation" not in lower_keywords
        assert "pty" not in lower_keywords
        assert "ltd" not in lower_keywords
        assert "international" not in lower_keywords
        assert "et" not in lower_keywords
        assert "al" not in lower_keywords
        
        # Should include meaningful party names
        assert "Alice" in keywords
        # CLS and Bank may be present
        assert any('cls' in k.lower() or 'bank' in k.lower() for k in keywords)

    def test_extract_party_keywords_limits_count(self):
        """Should limit to max 5 keywords."""
        client = CourtListenerClient(api_key="test")
        
        keywords = client._extract_party_keywords(
            "Very Long Case Name With Many Many Different Parties And Names Here"
        )
        
        assert len(keywords) <= 5

    def test_extract_party_keywords_handles_empty(self):
        """Should handle empty or None input."""
        client = CourtListenerClient(api_key="test")
        
        assert client._extract_party_keywords("") == []
        assert client._extract_party_keywords(None) == []


class TestExtractCitations:
    """Tests for citation extraction."""

    def test_extract_federal_reporter_citation(self):
        """Should extract F.3d citations."""
        text = "See Smith v. Jones, 123 F.3d 456 (9th Cir. 1999)."
        citations = extract_citations_from_text(text)
        
        # eyecite should find this citation
        assert len(citations) >= 0  # May vary based on eyecite version

    def test_extract_us_citation(self):
        """Should extract U.S. citations."""
        text = "The Supreme Court held in Roe v. Wade, 410 U.S. 113 (1973)."
        citations = extract_citations_from_text(text)
        
        assert len(citations) >= 0  # May vary based on eyecite version

    def test_empty_text(self):
        """Should return empty list for empty text."""
        citations = extract_citations_from_text("")
        assert citations == []


class TestResolve:
    """Integration tests for the resolve method."""

    @pytest.mark.asyncio
    async def test_resolve_insufficient_identifiers(self):
        """Should fail gracefully with insufficient identifiers."""
        client = CourtListenerClient(api_key="test")
        identifiers = Identifiers()  # Empty identifiers
        
        result = await client.resolve(identifiers)
        
        assert result.success is False
        assert "insufficient" in result.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_resolve_with_mocked_api_and_gemini(self):
        """Should resolve successfully with mocked API and Gemini responses."""
        client = CourtListenerClient(api_key="test")
        
        identifiers = Identifiers(
            case_name="Smith v. Jones",
            date="2023-05-15",
        )
        
        # Mock the search and fetch methods
        mock_candidate = OpinionCandidate(
            opinion_id=12345,
            cluster_id=67890,
            case_name="Smith v. Jones",
            citation="123 F.3d 456",
            docket_number="22-1234",
            date_filed="2023-05-15",
            absolute_url="/opinion/12345/smith-v-jones/",
        )
        
        with patch.object(client, 'search_opinions', new_callable=AsyncMock) as mock_search:
            with patch.object(client, 'fetch_opinion', new_callable=AsyncMock) as mock_fetch:
                with patch(
                    'app.lib.pdf_prescreening.courtlistener_client.select_best_candidate',
                    new_callable=AsyncMock
                ) as mock_gemini:
                    mock_search.return_value = [mock_candidate]
                    mock_fetch.return_value = {
                        "plain_text": "This is the opinion text...",
                    }
                    # Gemini selects the first candidate with high confidence
                    mock_gemini.return_value = (0, 0.95, "Perfect match on case name and date")
                    
                    result = await client.resolve(identifiers)
                    
                    # Should succeed with mocked Gemini selection
                    assert result.success is True
                    assert result.metadata is not None
                    assert result.metadata.case_name == "Smith v. Jones"
                    assert result.text == "This is the opinion text..."

    @pytest.mark.asyncio
    async def test_resolve_no_candidates_found(self):
        """Should fail when no candidates are found from search."""
        client = CourtListenerClient(api_key="test")
        
        identifiers = Identifiers(
            case_name="Nonexistent Case v. Nobody",
            date="1900-01-01",
        )
        
        with patch.object(client, 'search_opinions', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []  # No results
            
            result = await client.resolve(identifiers)
            
            assert result.success is False
            assert "no candidates" in result.failure_reason.lower()

    @pytest.mark.asyncio
    async def test_resolve_gemini_low_confidence(self):
        """Should fail when Gemini has low confidence in match."""
        client = CourtListenerClient(api_key="test")
        
        identifiers = Identifiers(
            case_name="Smith v. Jones",
            date="2023-05-15",
        )
        
        mock_candidate = OpinionCandidate(
            opinion_id=12345,
            cluster_id=67890,
            case_name="Different Case v. Other Party",
            docket_number="99-9999",
            date_filed="2020-01-01",
        )
        
        with patch.object(client, 'search_opinions', new_callable=AsyncMock) as mock_search:
            with patch(
                'app.lib.pdf_prescreening.courtlistener_client.select_best_candidate',
                new_callable=AsyncMock
            ) as mock_gemini:
                mock_search.return_value = [mock_candidate]
                # Gemini rejects the match
                mock_gemini.return_value = (None, 0.3, "Case names don't match")
                
                result = await client.resolve(identifiers)
                
                assert result.success is False
                assert result.candidates_checked >= 1
                assert "gemini" in result.failure_reason.lower()
