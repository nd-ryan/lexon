# PDF Pre-screening for Bulk Upload

This document describes the PDF pre-screening pipeline that handles flattened (image-only) PDFs in the admin bulk upload flow.

## Overview

When uploading PDFs through the admin bulk upload page, the system automatically pre-screens each PDF to determine if it has a usable text layer. For PDFs without a text layer (flattened/scanned documents), the system attempts to:

1. **Resolve via CourtListener**: Match the document to a known U.S. case/opinion and fetch canonical text
2. **Fall back to OCR**: Extract text using iLovePDF OCR if CourtListener resolution fails

This approach avoids expensive full-document OCR when possible by leveraging existing canonical sources.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Admin selects PDF files                                            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Pre-screening Pipeline (per file)                                  │
│  1. Extract text via iLovePDF extract task                          │
│  2. Assess text quality                                             │
│     └─► If clearly good: return text_layer_ok (skip Gemini)         │
│  3. If borderline: Analyze with Gemini (visual comparison)          │
│     └─► Extract identifiers (case name, court, date, citations)     │
│  4. If flattened: Query CourtListener with identifiers              │
│     └─► If match found: return courtlistener_resolved               │
│  5. Fall back to iLovePDF OCR                                       │
│     └─► return ocr_resolved or failed                               │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Admin reviews CourtListener/OCR results (if applicable)            │
│  - Side-by-side comparison with original PDF                        │
│  - Confirm or reject resolved text                                  │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Existing bulk upload pipeline                                      │
│  - Upload file + prescreened text to backend                        │
│  - AI extraction uses prescreened text                              │
│  - Save to Postgres, upload to KG                                   │
└─────────────────────────────────────────────────────────────────────┘
```

## Text Source Types

Each processed document has a `text_source` field indicating where the text came from:

| Value | Description |
|-------|-------------|
| `pdf_text` | Text extracted directly from PDF's text layer via iLovePDF |
| `courtlistener` | Canonical opinion text fetched from CourtListener |
| `ocr` | Text extracted from images via iLovePDF OCR |

## Text Quality Assessment

For efficiency, prescreening only extracts the **first 4 pages** (configurable via `PRESCREENING_MAX_EXTRACT_PAGES`) to assess quality. This speeds up the process significantly for large PDFs.

The system assesses text quality using these heuristics on the sampled pages:

- **Total character count**: >= 1500 characters
- **Per-page distribution**: At least 50% of sampled pages have >= 150 characters
- **Printable ratio**: >= 95% printable characters
- **Alphabetic ratio**: >= 50% alphabetic characters (legal docs are text-heavy)
- **Junk pattern detection**: No `(cid:X)` patterns or PDF binary/stream patterns in text

If quality is borderline, the document is sent to Gemini for visual comparison.

## Gemini Visual Comparison

When the text quality is borderline (not clearly good or bad), Gemini is used to compare:
- The **visual content** of the PDF pages (rendered as images)
- The **extracted text** from iLovePDF

This catches cases where a PDF has a text layer that extracts garbage (e.g., `(cid:X)` patterns that represent embedded fonts incorrectly).

Gemini also extracts document identifiers for CourtListener resolution.

## CourtListener Resolution

For flattened PDFs, the system attempts to match the document to a CourtListener opinion:

### Identifier Extraction

Gemini analyzes the first 4 pages as images (configurable via `PRESCREENING_MAX_ANALYSIS_PAGES`) to extract:
- Case name (e.g., "Smith v. Jones")
- Court name
- Decision date
- Docket number
- Legal citations (e.g., "123 F.3d 456")

### Query Strategies

The system builds search queries focusing on case name keywords and docket numbers (which are more reliable than citation matching):

1. **Party keyword search**: Extract key party names (e.g., "Alice CLS Bank" from "ALICE CORPORATION PTY. LTD. v. CLS BANK INTERNATIONAL ET AL.") with date constraints
2. **Docket number search**: `docketNumber:"13-298" dateFiled:[2014-01-01 TO 2014-12-31]`
3. **Broader keyword fallback**: Party names without date constraints

### Candidate Selection (Gemini-based)

Instead of programmatic scoring, the system uses Gemini to select the best matching candidate. This is more robust because Gemini can:
- Handle name variations (e.g., "Alice Corp." vs "Alice Corporation Pty. Ltd.")
- Understand that "v." and "vs." are equivalent
- Match core party names even with different corporate suffixes

Gemini evaluates candidates and returns a confidence score (0.0-1.0). A match is accepted if confidence >= 0.75.

### Acceptance Criteria

A candidate is accepted if Gemini's confidence score is >= 0.75.

### Rate Limiting

The CourtListener client includes:
- 0.5 second delay between search queries
- Retry logic with exponential backoff for 403/rate-limit errors
- User-Agent header to identify the application

## Configuration

Environment variables (in `ai-backend/.env`):

```bash
# Required - iLovePDF
ILOVEPDF_PUBLIC_KEY=...         # iLovePDF API public key
ILOVEPDF_SECRET_KEY=...         # iLovePDF API secret key

# Required - Gemini (for visual comparison)
GEMINI_API_KEY=...              # For Gemini vision calls (via litellm)

# Required - CourtListener
COURT_LISTENER_API_KEY=...      # CourtListener API authentication (get from https://www.courtlistener.com/profile/api/)

# Optional (with defaults)
ILOVEPDF_TIMEOUT=300.0                # HTTP timeout for iLovePDF API (seconds, default 300s for OCR)
PRESCREENING_MIN_CHARS=1500           # Minimum chars for good quality
PRESCREENING_MIN_PAGE_CHARS=150       # Minimum chars per page
PRESCREENING_MIN_ALPHA_RATIO=0.50     # Minimum alphabetic character ratio
PRESCREENING_RESOLVER_ACCEPT_SCORE=0.75  # Minimum Gemini confidence to accept match
PRESCREENING_MAX_RETRIES=3            # Max retries for CourtListener API
PRESCREENING_RETRY_DELAY=1.0          # Initial retry delay in seconds
PRESCREENING_GEMINI_MODEL=gemini/gemini-2.5-flash  # Model for visual comparison + candidate selection
PRESCREENING_MAX_EXTRACT_PAGES=4      # Pages to extract for quality check
PRESCREENING_MAX_ANALYSIS_PAGES=4     # Pages to send to Gemini for visual analysis
```

## API Endpoints

### Pre-screen PDF

```
POST /api/ai/prescreening/analyze
Content-Type: multipart/form-data

file: <PDF file>
```

Response:
```json
{
  "status": "courtlistener_resolved",
  "text": "The court finds that...",
  "text_source": "courtlistener",
  "confidence": 0.87,
  "courtlistener_metadata": {
    "opinion_id": 12345,
    "cluster_id": 67890,
    "case_name": "Smith v. Jones",
    "court": "ca9",
    "date_filed": "2023-05-15",
    "docket_number": "22-1234",
    "citation": "123 F.3d 456",
    "canonical_url": "https://www.courtlistener.com/opinion/12345/smith-v-jones/",
    "resolver_confidence": 0.87
  },
  "warnings": ["Text length differs by 15% from expected"],
  "error": null
}
```

### Upload with Prescreened Text

```
POST /api/ai/cases/upload
Content-Type: multipart/form-data

file: <PDF file>
prescreened_text: <text from prescreening>
text_source: courtlistener|ocr
```

## Frontend Usage

The admin bulk upload page (`/admin/bulk-upload`) automatically:

1. Pre-screens each selected PDF before enabling the "Start Processing" button
2. Shows status indicators:
   - ✓ Text layer OK (green)
   - ⚠️ Resolved via CourtListener (amber) - needs review
   - ⚠️ Resolved via OCR (amber) - needs review
   - ✗ Failed (red) - blocked
3. Allows admins to review resolved text before confirming
4. Passes prescreened text to the extraction pipeline
5. **Skips failed files**: Files that fail prescreening are automatically excluded from processing

### Timeouts

- Frontend prescreening requests have a **15-minute timeout** to accommodate OCR of long documents
- Files are processed sequentially (concurrency = 1) to avoid overwhelming external APIs
- If prescreening times out, the file is marked as failed and will be skipped during processing

## Module Structure

```
ai-backend/app/lib/pdf_prescreening/
├── __init__.py              # Public exports
├── models.py                # Pydantic models
├── ilovepdf_client.py       # Text extraction (iLovePDF extract) + OCR (iLovePDF pdfocr)
├── gemini_analyzer.py       # Gemini vision for visual comparison + identifier extraction + candidate selection
├── courtlistener_client.py  # CourtListener API client (fuzzy search + Gemini matching)
├── text_extractor.py        # pdfplumber utilities (first page extraction for eyecite)
└── pipeline.py              # Main orchestration
```

## Testing

Run unit tests:
```bash
cd ai-backend
poetry run pytest tests/lib/pdf_prescreening/ -v
```

## Limitations

- **U.S. cases only**: CourtListener resolution only works for U.S. federal and state court opinions
- **No OCR for non-legal documents**: The system assumes all PDFs are legal documents
- **Rate limits**: CourtListener has API rate limits (~5000 requests/day for authenticated users)
- **iLovePDF API limits**: iLovePDF has usage limits based on subscription tier

## Future Improvements

- Add support for non-U.S. legal document sources
- Implement caching for CourtListener lookups by PDF hash
- Support user confirmation UI for ambiguous matches
