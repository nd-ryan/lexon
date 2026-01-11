"""CourtListener API client for opinion resolution."""

import os
import re
import asyncio
import logging
from typing import Optional

import httpx
from eyecite import get_citations

from .models import Identifiers, OpinionCandidate, CourtListenerMetadata, ResolutionResult
from .gemini_analyzer import select_best_candidate

# Use the shared prescreening logger (configured in __init__.py)
logger = logging.getLogger("prescreening")

# Configuration
COURT_LISTENER_API_KEY = os.getenv("COURT_LISTENER_API_KEY", "")
# CourtListener API v4 - updated from v3 which is deprecated
COURT_LISTENER_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
# Minimum confidence from Gemini to accept a match
RESOLVER_ACCEPT_SCORE = float(os.getenv("PRESCREENING_RESOLVER_ACCEPT_SCORE", "0.75"))
MAX_SEARCH_QUERIES = int(os.getenv("PRESCREENING_MAX_QUERIES", "3"))
REQUEST_TIMEOUT = float(os.getenv("PRESCREENING_REQUEST_TIMEOUT", "30.0"))
MAX_RETRIES = int(os.getenv("PRESCREENING_MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("PRESCREENING_RETRY_DELAY", "1.0"))


class CourtListenerClient:
    """Client for interacting with CourtListener API."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or COURT_LISTENER_API_KEY
        self.base_url = COURT_LISTENER_BASE_URL
        
        if not self.api_key:
            logger.warning(
                "No CourtListener API key configured. "
                "Set COURT_LISTENER_API_KEY env var. "
                "API calls will be rate-limited as anonymous requests."
            )
    
    def _get_headers(self) -> dict:
        """Get headers for API requests."""
        headers = {
            "Content-Type": "application/json",
            # User-Agent helps avoid being blocked as a bot
            "User-Agent": "Lexon-Legal-Research/1.0 (legal research application)",
        }
        if self.api_key:
            headers["Authorization"] = f"Token {self.api_key}"
        return headers
    
    async def search_opinions(self, query: str, max_results: int = 10) -> list[OpinionCandidate]:
        """
        Search CourtListener for opinions matching query.
        
        Includes retry logic with exponential backoff for rate limiting (403 errors).
        
        Args:
            query: Search query string
            max_results: Maximum results to return
            
        Returns:
            List of OpinionCandidate objects
        """
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    response = await client.get(
                        f"{self.base_url}/search/",
                        params={
                            "q": query,
                            "type": "o",  # opinions
                            "order_by": "score desc",
                        },
                        headers=self._get_headers(),
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    candidates = []
                    results = data.get("results", [])[:max_results]
                    
                    for result in results:
                        try:
                            # API v4: opinion_id is inside the "opinions" array, not at top level
                            # The top-level "id" field doesn't exist - we have cluster_id instead
                            opinions_list = result.get("opinions", [])
                            opinion_id = opinions_list[0].get("id", 0) if opinions_list else 0
                            
                            candidate = OpinionCandidate(
                                opinion_id=opinion_id,
                                cluster_id=result.get("cluster_id", 0),
                                case_name=result.get("caseName", "") or result.get("case_name", ""),
                                court=result.get("court", ""),
                                date_filed=result.get("dateFiled", "") or result.get("date_filed", ""),
                                docket_number=result.get("docketNumber", "") or result.get("docket_number", ""),
                                citation=self._extract_primary_citation(result),
                                absolute_url=result.get("absolute_url", ""),
                            )
                            candidates.append(candidate)
                        except Exception as e:
                            logger.warning(f"Failed to parse search result: {e}")
                            continue
                    
                    return candidates
                    
            except httpx.HTTPStatusError as e:
                last_error = e
                status_code = e.response.status_code
                
                # Log specific guidance for common errors
                if status_code == 403:
                    if not self.api_key:
                        logger.warning(
                            "CourtListener 403 Forbidden - likely due to missing API key. "
                            "Anonymous requests have stricter rate limits. "
                            "Set COURT_LISTENER_API_KEY env var for higher limits."
                        )
                    else:
                        logger.warning(
                            "CourtListener 403 Forbidden - API key may be invalid or rate limited. "
                            "Check your API key at https://www.courtlistener.com/profile/api/"
                        )
                
                # Retry on rate limiting (403, 429) or server errors (5xx)
                if status_code in (403, 429, 500, 502, 503, 504) and attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY * (2 ** attempt)  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(
                        f"CourtListener returned {status_code}, "
                        f"retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(f"CourtListener search failed: {e}")
                return []
            except httpx.HTTPError as e:
                logger.error(f"CourtListener search failed: {e}")
                return []
        
        if last_error:
            logger.error(f"CourtListener search failed after {MAX_RETRIES} retries: {last_error}")
        return []
    
    async def fetch_opinion(self, opinion_id: int) -> Optional[dict]:
        """
        Fetch full opinion details including text.
        
        Args:
            opinion_id: CourtListener opinion ID
            
        Returns:
            Opinion data dict, or None if fetch fails
        """
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(
                    f"{self.base_url}/opinions/{opinion_id}/",
                    headers=self._get_headers(),
                )
                response.raise_for_status()
                return response.json()
                
        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch opinion {opinion_id}: {e}")
            return None
    
    async def resolve(self, identifiers: Identifiers) -> ResolutionResult:
        """
        Attempt to resolve identifiers to a CourtListener opinion.
        
        Args:
            identifiers: Extracted document identifiers
            
        Returns:
            ResolutionResult with success status and opinion data if found
        """
        if not identifiers.has_sufficient_data():
            return ResolutionResult(
                success=False,
                failure_reason="Insufficient identifiers for resolution",
            )
        
        # Build search queries from identifiers
        queries = self._build_search_queries(identifiers)
        
        if not queries:
            return ResolutionResult(
                success=False,
                failure_reason="Could not construct search queries from identifiers",
            )
        
        # Search and collect all candidates
        all_candidates: list[OpinionCandidate] = []
        seen_ids: set[int] = set()
        
        for i, query in enumerate(queries[:MAX_SEARCH_QUERIES]):
            # Add delay between queries to avoid rate limiting
            if i > 0:
                await asyncio.sleep(0.5)
            
            logger.info(f"CourtListener search: {query}")
            candidates = await self.search_opinions(query)
            
            for candidate in candidates:
                if candidate.opinion_id not in seen_ids:
                    seen_ids.add(candidate.opinion_id)
                    all_candidates.append(candidate)
        
        if not all_candidates:
            return ResolutionResult(
                success=False,
                candidates_checked=0,
                failure_reason="No candidates found from CourtListener search",
            )
        
        # Use Gemini to select the best matching candidate
        # This is more robust than programmatic scoring for handling name variations
        candidate_dicts = [
            {
                "case_name": c.case_name,
                "court": c.court,
                "date_filed": c.date_filed,
                "docket_number": c.docket_number,
            }
            for c in all_candidates[:10]  # Limit to top 10 candidates for Gemini
        ]
        
        logger.info(f"Asking Gemini to select from {len(candidate_dicts)} candidates")
        selected_index, confidence, reasoning = await select_best_candidate(
            identifiers, candidate_dicts
        )
        
        logger.info(f"Gemini selection: index={selected_index}, confidence={confidence:.2f}, reason={reasoning}")
        
        # Check if Gemini found a match with sufficient confidence
        if selected_index is None or confidence < RESOLVER_ACCEPT_SCORE:
            # Fall back: log top candidates for debugging
            top_candidates_info = [
                f"{c.case_name} ({c.docket_number or 'no docket'})"
                for c in all_candidates[:3]
            ]
            logger.info(f"Top candidates were: {top_candidates_info}")
            
            return ResolutionResult(
                success=False,
                candidates_checked=len(all_candidates),
                top_candidates=all_candidates[:3],
                failure_reason=f"Gemini could not confidently match (confidence={confidence:.2f}): {reasoning}",
            )
        
        top_candidate = all_candidates[selected_index]
        top_candidate.score = confidence
        
        logger.info(f"Gemini selected: {top_candidate.case_name} with confidence {confidence:.2f}")
        
        # Fetch full opinion text
        opinion_data = await self.fetch_opinion(top_candidate.opinion_id)
        
        if not opinion_data:
            return ResolutionResult(
                success=False,
                candidates_checked=len(all_candidates),
                top_candidates=all_candidates[:3],
                failure_reason="Failed to fetch opinion text from CourtListener",
            )
        
        # Extract text (prefer plain_text, fall back to html_with_citations stripped)
        opinion_text = opinion_data.get("plain_text", "")
        if not opinion_text:
            html_text = opinion_data.get("html_with_citations", "") or opinion_data.get("html", "")
            opinion_text = self._strip_html(html_text)
        
        if not opinion_text:
            return ResolutionResult(
                success=False,
                candidates_checked=len(all_candidates),
                top_candidates=all_candidates[:3],
                failure_reason="Opinion has no text content",
            )
        
        # Build metadata
        canonical_url = f"https://www.courtlistener.com{top_candidate.absolute_url}" if top_candidate.absolute_url else f"https://www.courtlistener.com/opinion/{top_candidate.opinion_id}/"
        
        metadata = CourtListenerMetadata(
            opinion_id=top_candidate.opinion_id,
            cluster_id=top_candidate.cluster_id,
            case_name=top_candidate.case_name,
            court=top_candidate.court,
            date_filed=top_candidate.date_filed,
            docket_number=top_candidate.docket_number,
            citation=top_candidate.citation,
            canonical_url=canonical_url,
            resolver_confidence=confidence,
        )
        
        return ResolutionResult(
            success=True,
            metadata=metadata,
            text=opinion_text,
            candidates_checked=len(all_candidates),
            top_candidates=all_candidates[:3],
        )
    
    def _build_search_queries(self, identifiers: Identifiers) -> list[str]:
        """
        Build search queries from identifiers.
        
        Strategy: 
        1. Try citation-based lookups first (most reliable)
        2. Fall back to party name + docket number searches
        """
        queries = []
        
        # Query 0: Direct citation lookup (most reliable when we have a good citation)
        # Citations like "325 U.S. 797" can be searched directly
        if identifiers.citations:
            for citation in identifiers.citations[:2]:  # Try first 2 citations
                # Only use citations that look like reporter citations (e.g., "123 U.S. 456")
                # Skip malformed citations or section symbols
                if re.match(r'^\d+\s+[\w\.\s]+\s+\d+', citation):
                    queries.append(f'citation:"{citation}"')
        
        # Extract party names from case name for fuzzy search
        party_keywords = self._extract_party_keywords(identifiers.case_name) if identifiers.case_name else []
        
        # Query 1: Party names as keywords + year constraint
        # Search for "Alice CLS Bank" rather than exact case name
        if party_keywords:
            keyword_query = " ".join(party_keywords)
            if identifiers.date:
                year_match = re.search(r'\d{4}', identifiers.date)
                if year_match:
                    year = year_match.group()
                    queries.append(f'{keyword_query} dateFiled:[{year}-01-01 TO {year}-12-31]')
                else:
                    queries.append(keyword_query)
            else:
                queries.append(keyword_query)
        
        # Query 2: Docket number (very reliable when present)
        if identifiers.docket_number:
            # Clean docket number - just the number part
            docket_clean = re.sub(r'^No\.\s*', '', identifiers.docket_number, flags=re.IGNORECASE)
            if identifiers.date:
                year_match = re.search(r'\d{4}', identifiers.date)
                if year_match:
                    year = year_match.group()
                    queries.append(f'docketNumber:"{docket_clean}" dateFiled:[{year}-01-01 TO {year}-12-31]')
            else:
                queries.append(f'docketNumber:"{docket_clean}"')
        
        # Query 3: Broader party keyword search without date constraint
        if party_keywords and len(queries) < 4:
            queries.append(" ".join(party_keywords[:3]))  # Use top 3 party keywords
        
        return queries
    
    def _extract_party_keywords(self, case_name: str) -> list[str]:
        """
        Extract significant party name keywords from a case name.
        
        "ALICE CORPORATION PTY. LTD. v. CLS BANK INTERNATIONAL ET AL."
        -> ["Alice", "CLS", "Bank"]
        """
        if not case_name:
            return []
        
        # Common terms to filter out
        stopwords = {
            'v', 'vs', 'versus', 'et', 'al', 'in', 're', 'the', 'of', 'and', 'for',
            'inc', 'corp', 'corporation', 'company', 'co', 'ltd', 'llc', 'llp', 'lp',
            'pty', 'plc', 'sa', 'na', 'usa', 'us', 'united', 'states', 'america',
            'international', 'intl', 'national', 'natl', 'group', 'holdings',
        }
        
        # Split on common delimiters
        parts = re.split(r'[\s,\.]+', case_name)
        
        # Filter and collect meaningful keywords
        keywords = []
        for part in parts:
            # Clean and lowercase for comparison
            clean = re.sub(r'[^\w]', '', part)
            if not clean:
                continue
            
            # Skip stopwords and short words
            if clean.lower() in stopwords or len(clean) < 3:
                continue
            
            # Capitalize properly for search
            keywords.append(clean.capitalize())
        
        # Return unique keywords, preserving order
        seen = set()
        unique = []
        for kw in keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                unique.append(kw)
        
        return unique[:5]  # Limit to 5 most significant keywords
    
    def _extract_primary_citation(self, result: dict) -> Optional[str]:
        """Extract primary citation from search result."""
        # Try various citation fields
        citation = result.get("citation", [])
        if isinstance(citation, list) and citation:
            return citation[0]
        if isinstance(citation, str):
            return citation
        
        # Try lexisCite or other fields
        for field in ["lexisCite", "neutralCite"]:
            if result.get(field):
                return result[field]
        
        return None
    
    def _strip_html(self, html: str) -> str:
        """Strip HTML tags from text."""
        import re
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', html)
        # Decode common entities
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")
        text = text.replace('&nbsp;', ' ')
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


def extract_citations_from_text(text: str) -> list[str]:
    """
    Extract legal citations from text using eyecite.
    
    Args:
        text: Text to extract citations from
        
    Returns:
        List of citation strings (actual citation text, not repr)
    """
    try:
        from eyecite.models import FullCaseCitation, ShortCaseCitation
        
        citations = get_citations(text)
        result = []
        
        for c in citations:
            # Only extract full case citations (e.g., "123 U.S. 456")
            # Skip UnknownCitation (section symbols, etc.), IdCitation, SupraCitation
            if isinstance(c, (FullCaseCitation, ShortCaseCitation)):
                # Use matched_text() to get the actual citation string from the text
                if hasattr(c, 'matched_text') and callable(c.matched_text):
                    matched = c.matched_text()
                    if matched:
                        result.append(matched)
                # Fallback: reconstruct from groups if available
                elif hasattr(c, 'groups') and c.groups:
                    g = c.groups
                    volume = g.get('volume', '')
                    reporter = g.get('reporter', '')
                    page = g.get('page', '')
                    if volume and reporter and page:
                        result.append(f"{volume} {reporter} {page}".strip())
        
        # Return unique citations, preserving order
        seen = set()
        unique = []
        for cit in result:
            if cit not in seen:
                seen.add(cit)
                unique.append(cit)
        
        return unique
    except Exception as e:
        logger.warning(f"Citation extraction failed: {e}")
        return []
