"""Gemini vision analyzer for flattened PDFs."""

import os
import json
import base64
import logging
from io import BytesIO
from typing import Optional

from litellm import acompletion
from pdf2image import convert_from_bytes
from PIL import Image

from .models import GeminiAnalysisResult, Identifiers

# Use the shared prescreening logger (configured in __init__.py)
logger = logging.getLogger("prescreening")

# Configuration
# Use Flash for faster/cheaper processing - sufficient for text comparison and identifier extraction
# Can override to Pro via PRESCREENING_GEMINI_MODEL if needed
GEMINI_MODEL = os.getenv("PRESCREENING_GEMINI_MODEL", "gemini/gemini-2.5-flash")
MAX_PAGES_FOR_ANALYSIS = int(os.getenv("PRESCREENING_MAX_ANALYSIS_PAGES", "4"))
MAX_PAGES_FOR_OCR = int(os.getenv("PRESCREENING_MAX_OCR_PAGES", "200"))
IMAGE_DPI = int(os.getenv("PRESCREENING_IMAGE_DPI", "150"))
MAX_IMAGE_DIMENSION = int(os.getenv("PRESCREENING_MAX_IMAGE_DIM", "1568"))

# Prompts
ANALYSIS_PROMPT_TEMPLATE = """You are analyzing pages from a legal document PDF to determine if text extraction will work properly.

IMPORTANT: I will show you:
1. Rendered images of the PDF pages (what the document looks like visually)
2. The text that was extracted from the PDF's text layer (if any)

Your tasks:
1. Compare the VISUAL text in the images to the EXTRACTED text below
2. Determine if the extracted text is USABLE or GARBAGE
3. Extract any legal document identifiers you can see in the images

EXTRACTED TEXT FROM PDF (first 1000 chars):
---
{extracted_text}
---

If the extracted text:
- Contains readable words that match what you see in the images → is_flattened = false
- Contains garbage like "(cid:X)", random symbols, or doesn't match the visual text → is_flattened = true
- Is empty or nearly empty → is_flattened = true

Look for these identifiers in the IMAGES:
- Case name (e.g., "Smith v. Jones", "In re XYZ Corp")
- Court name (e.g., "United States Court of Appeals for the Ninth Circuit")
- Decision date
- Docket number (e.g., "No. 22-1234")
- Citations (e.g., "123 F.3d 456", "456 U.S. 789")

Respond ONLY with valid JSON in this exact format:
{{
  "is_flattened": true,
  "confidence": 0.95,
  "text_quality_reason": "Extracted text contains (cid:X) patterns which is garbage",
  "identifiers": {{
    "case_name": "Smith v. Jones",
    "court": "United States Court of Appeals for the Ninth Circuit",
    "date": "2023-05-15",
    "docket_number": "No. 22-1234",
    "citations": ["123 F.3d 456"]
  }}
}}

Notes:
- is_flattened means the text extraction is NOT usable (even if there's technically a text layer)
- confidence should be 0.0-1.0 based on how certain you are
- For identifiers, use null for any fields you cannot find
- For date, prefer YYYY-MM-DD format if possible"""

OCR_PROMPT = """You are extracting text from a scanned legal document.

Please transcribe ALL visible text from this page exactly as it appears, maintaining:
- Paragraph structure
- Headers and section breaks
- Any numbered or bulleted lists
- Legal citations and case references

Preserve the document's formatting as much as possible using plain text.
Do NOT summarize or interpret - just transcribe the visible text."""

CANDIDATE_SELECTION_PROMPT = """You are helping match a legal document to its record in the CourtListener database.

I have a PDF document with these identifiers:
- Case Name: {case_name}
- Court: {court}
- Date: {date}
- Docket Number: {docket_number}

Here are candidate matches from CourtListener:
{candidates_text}

Your task:
1. Compare each candidate to the document identifiers
2. Determine which candidate (if any) is the SAME case as the document
3. Be flexible with name variations (e.g., "Alice Corp." vs "Alice Corporation Pty. Ltd.")
4. Focus on matching the core parties (e.g., "Alice" and "CLS Bank") 
5. Docket numbers and dates should match if both are available

IMPORTANT: 
- Only select a match if you are CONFIDENT it's the same case
- Different cases from the same parties should NOT match
- If none are a good match, select "none"

Respond ONLY with valid JSON:
{{
  "selected_index": 0,
  "confidence": 0.95,
  "reasoning": "Case names match (Alice Corp v CLS Bank), docket number matches (13-298), and date matches (2014)"
}}

Or if no match:
{{
  "selected_index": null,
  "confidence": 0.0,
  "reasoning": "None of the candidates match the document identifiers"
}}"""


async def analyze_pdf_images(
    pdf_bytes: bytes, 
    extracted_text: str = "",
    max_pages: int = MAX_PAGES_FOR_ANALYSIS
) -> GeminiAnalysisResult:
    """
    Render first N pages as images and analyze with Gemini.
    
    Compares the visual content of the PDF against the extracted text
    to determine if the text extraction is usable or garbage.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        extracted_text: Text extracted via pdfplumber (for comparison)
        max_pages: Maximum number of pages to analyze
        
    Returns:
        GeminiAnalysisResult with flattened assessment and identifiers
    """
    try:
        # Convert PDF pages to images
        images = _convert_pdf_to_images(pdf_bytes, max_pages=max_pages)
        
        if not images:
            return GeminiAnalysisResult(
                is_flattened=True,
                confidence=0.5,
                identifiers=Identifiers(),
                raw_response="Failed to convert PDF to images",
            )
        
        # Prepare the prompt with extracted text sample
        text_sample = extracted_text[:1000] if extracted_text else "(no text extracted)"
        prompt = ANALYSIS_PROMPT_TEMPLATE.format(extracted_text=text_sample)
        
        # Build multimodal message content
        content = [{"type": "text", "text": prompt}]
        for img in images:
            b64_image = _image_to_base64(img)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64_image}"}
            })
        
        # Call Gemini via litellm
        response = await acompletion(
            model=GEMINI_MODEL,
            messages=[{"role": "user", "content": content}],
            temperature=0,
        )
        
        raw_response = response.choices[0].message.content
        
        # Parse JSON response
        result = _parse_analysis_response(raw_response)
        result.raw_response = raw_response
        
        return result
        
    except Exception as e:
        logger.error(f"Gemini analysis failed: {e}", exc_info=True)
        return GeminiAnalysisResult(
            is_flattened=True,
            confidence=0.0,
            identifiers=Identifiers(),
            raw_response=f"Error: {str(e)}",
        )


async def extract_full_text_ocr(
    pdf_bytes: bytes,
    max_pages: Optional[int] = None
) -> str:
    """
    Full OCR fallback: render all pages and extract text via Gemini.
    
    Args:
        pdf_bytes: Raw PDF file bytes
        max_pages: Maximum pages to OCR (defaults to MAX_PAGES_FOR_OCR)
        
    Returns:
        Extracted text from all pages
    """
    max_pages = max_pages or MAX_PAGES_FOR_OCR
    
    try:
        # Convert all PDF pages to images
        images = _convert_pdf_to_images(pdf_bytes, max_pages=max_pages)
        
        if not images:
            logger.error("No images extracted from PDF for OCR")
            return ""
        
        # OCR each page
        page_texts: list[str] = []
        
        for i, img in enumerate(images):
            logger.info(f"OCR processing page {i + 1}/{len(images)}")
            
            b64_image = _image_to_base64(img)
            content = [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}
            ]
            
            try:
                response = await acompletion(
                    model=GEMINI_MODEL,
                    messages=[{"role": "user", "content": content}],
                    temperature=0,
                )
                
                page_text = response.choices[0].message.content or ""
                page_texts.append(page_text.strip())
                
            except Exception as e:
                logger.warning(f"OCR failed for page {i + 1}: {e}")
                page_texts.append(f"[OCR failed for page {i + 1}]")
        
        return "\n\n---\n\n".join(page_texts)
        
    except Exception as e:
        logger.error(f"Full OCR extraction failed: {e}", exc_info=True)
        return ""


async def select_best_candidate(
    identifiers: Identifiers,
    candidates: list[dict],
) -> tuple[int | None, float, str]:
    """
    Use Gemini to select the best matching candidate from CourtListener results.
    
    This is more robust than programmatic scoring because Gemini can:
    - Handle name variations (Alice Corp. vs Alice Corporation Pty. Ltd.)
    - Understand that "v." and "vs." are equivalent
    - Match core party names even with different suffixes
    
    Args:
        identifiers: Document identifiers extracted by Gemini
        candidates: List of candidate dicts with case_name, court, date_filed, docket_number
        
    Returns:
        Tuple of (selected_index or None, confidence, reasoning)
    """
    if not candidates:
        return None, 0.0, "No candidates to evaluate"
    
    # Build candidates text for the prompt
    candidates_text_parts = []
    for i, c in enumerate(candidates):
        candidates_text_parts.append(
            f"[{i}] Case: {c.get('case_name', 'Unknown')}\n"
            f"    Court: {c.get('court', 'Unknown')}\n"
            f"    Date: {c.get('date_filed', 'Unknown')}\n"
            f"    Docket: {c.get('docket_number', 'Unknown')}"
        )
    candidates_text = "\n\n".join(candidates_text_parts)
    
    prompt = CANDIDATE_SELECTION_PROMPT.format(
        case_name=identifiers.case_name or "Unknown",
        court=identifiers.court or "Unknown",
        date=identifiers.date or "Unknown",
        docket_number=identifiers.docket_number or "Unknown",
        candidates_text=candidates_text,
    )
    
    try:
        response = await acompletion(
            model=GEMINI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        
        raw_response = response.choices[0].message.content
        logger.info(f"Gemini candidate selection response: {raw_response}")
        
        # Parse JSON response
        json_str = raw_response.strip()
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            json_str = "\n".join(json_lines)
        
        data = json.loads(json_str)
        
        selected_index = data.get("selected_index")
        confidence = float(data.get("confidence", 0.0))
        reasoning = data.get("reasoning", "")
        
        # Validate selected_index
        if selected_index is not None:
            if not isinstance(selected_index, int) or selected_index < 0 or selected_index >= len(candidates):
                logger.warning(f"Invalid selected_index from Gemini: {selected_index}")
                return None, 0.0, f"Invalid index: {selected_index}"
        
        return selected_index, confidence, reasoning
        
    except Exception as e:
        logger.error(f"Gemini candidate selection failed: {e}", exc_info=True)
        return None, 0.0, f"Error: {str(e)}"


def _convert_pdf_to_images(pdf_bytes: bytes, max_pages: int) -> list[Image.Image]:
    """Convert PDF pages to PIL Images."""
    try:
        images = convert_from_bytes(
            pdf_bytes,
            dpi=IMAGE_DPI,
            first_page=1,
            last_page=max_pages,
        )
        
        # Resize if needed to stay within API limits
        resized = []
        for img in images:
            if max(img.size) > MAX_IMAGE_DIMENSION:
                ratio = MAX_IMAGE_DIMENSION / max(img.size)
                new_size = (int(img.width * ratio), int(img.height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            resized.append(img)
        
        return resized
        
    except Exception as e:
        logger.error(f"Failed to convert PDF to images: {e}")
        return []


def _image_to_base64(img: Image.Image) -> str:
    """Convert PIL Image to base64 string."""
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _parse_analysis_response(raw_response: str) -> GeminiAnalysisResult:
    """Parse Gemini's JSON response into GeminiAnalysisResult."""
    try:
        # Try to extract JSON from response (handle markdown code blocks)
        json_str = raw_response.strip()
        if json_str.startswith("```"):
            # Remove markdown code block
            lines = json_str.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                elif line.startswith("```") and in_block:
                    break
                elif in_block:
                    json_lines.append(line)
            json_str = "\n".join(json_lines)
        
        data = json.loads(json_str)
        
        # Extract identifiers
        id_data = data.get("identifiers", {}) or {}
        identifiers = Identifiers(
            case_name=id_data.get("case_name"),
            court=id_data.get("court"),
            date=id_data.get("date"),
            docket_number=id_data.get("docket_number"),
            citations=id_data.get("citations") or [],
        )
        
        return GeminiAnalysisResult(
            is_flattened=data.get("is_flattened", True),
            confidence=float(data.get("confidence", 0.5)),
            identifiers=identifiers,
        )
        
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse Gemini response: {e}")
        return GeminiAnalysisResult(
            is_flattened=True,
            confidence=0.5,
            identifiers=Identifiers(),
        )
