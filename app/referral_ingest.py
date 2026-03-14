from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _extract_pdf_text(data: bytes) -> str:
    try:
        import importlib
        pypdf = importlib.import_module("pypdf")
        pdf_reader = getattr(pypdf, "PdfReader")
    except Exception:
        return _decode_text(data)

    text_parts: list[str] = []
    try:
        reader = pdf_reader(BytesIO(data))
        for page in reader.pages:
            text_parts.append(page.extract_text() or "")
    except Exception:
        return _decode_text(data)
    return "\n".join(text_parts)


def _extract_docx_text(data: bytes) -> str:
    """Extract text from Word (.docx) files."""
    try:
        import importlib
        docx_module = importlib.import_module("docx")
        Document = getattr(docx_module, "Document")
    except Exception:
        return ""

    text_parts: list[str] = []
    try:
        doc = Document(BytesIO(data))
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text_parts.append(paragraph.text)
        
        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " ".join(cell.text for cell in row.cells)
                if row_text.strip():
                    text_parts.append(row_text)
    except Exception:
        return ""
    
    return "\n".join(text_parts)


def extract_referral_text(filename: str, data: bytes) -> tuple[str, list[str]]:
    ext = Path(filename or "").suffix.lower()
    warnings: list[str] = []

    if ext == ".pdf":
        text = _extract_pdf_text(data)
        if not text.strip():
            warnings.append("PDF text extraction returned no text. If this is a scan/image PDF, OCR is required.")
        return text, warnings

    if ext == ".docx":
        text = _extract_docx_text(data)
        if not text.strip():
            warnings.append("Word document text extraction returned no text. The file may be corrupted or empty.")
        return text, warnings

    if ext in {".txt", ".csv", ".json", ".xml", ".html", ".htm", ".md"}:
        return _decode_text(data), warnings

    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}:
        warnings.append("Image file uploaded. OCR is not enabled in this trial yet, so fields may be empty.")
        return "", warnings

    warnings.append("Unsupported file type. Supported: PDF, DOCX, TXT, CSV, JSON, HTML, or images.")
    return "", warnings


def _find_value(text: str, patterns: list[str], context_lines: int = 1) -> str:
    """
    Find a value using multiple regex patterns.
    Returns the longest non-empty match (better for catching full information).
    """
    matches: list[str] = []
    
    for pattern in patterns:
        try:
            results = re.finditer(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
            for match in results:
                value = (match.group(1) or "").strip(" \t:-\n\r")
                # Clean up the value: remove multiple spaces, limit to first 200 chars
                value = " ".join(value.split())[:200]
                if value and len(value) > 2:  # Avoid single-char matches
                    matches.append(value)
        except Exception:
            continue
    
    # Return longest match (usually most complete)
    if matches:
        matches.sort(key=len, reverse=True)
        return matches[0]
    return ""


def _split_name(full_name: str) -> tuple[str, str]:
    cleaned = " ".join((full_name or "").split())
    if not cleaned:
        return "", ""
    parts = cleaned.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def parse_referral_attachment(filename: str, data: bytes) -> dict:
    text, warnings = extract_referral_text(filename, data)

    # More comprehensive patterns for each field
    full_name = _find_value(text, [
        r"patient\s+name\s*[:\-]\s*([^\n\r]+)",
        r"^name\s*[:\-]\s*([^\n\r]+)",
        r"patient['\"]?\s+['\"]?name['\"]?\s*[:\-]\s*([^\n\r]+)",
    ])
    
    first_name = _find_value(text, [
        r"first\s+name\s*[:\-]\s*([^\n\r]+)",
        r"given\s+name\s*[:\-]\s*([^\n\r]+)",
        r"forename\s*[:\-]\s*([^\n\r]+)",
    ])
    
    surname = _find_value(text, [
        r"(?:surname|last\s+name|family\s+name)\s*[:\-]\s*([^\n\r]+)",
    ])

    # If we only have full name, split it
    if not first_name and not surname and full_name:
        first_name, surname = _split_name(full_name)

    patient_identifier = _find_value(text, [
        r"(?:nhs|hospital)\s+number\s*[:\-]\s*([^\n\r]+)",
        r"patient\s+(?:id|no\.?|number)\s*[:\-]\s*([^\n\r]+)",
        r"(?:mrn|medical\s+record)\s*(?:id|number)?\s*[:\-]\s*([^\n\r]+)",
        r"identifier\s*[:\-]\s*([^\n\r]+)",
    ])

    referral_reference = _find_value(text, [
        r"referral\s+(?:id|no\.?|number)\s*[:\-]\s*([^\n\r]+)",
        r"ref(?:erence)?\s+(?:id|no\.?|number)\s*[:\-]\s*([^\n\r]+)",
    ])
    
    dob = _find_value(text, [
        r"(?:dob|d\.o\.b|date\s+of\s+birth)\s*[:\-]\s*([^\n\r]+)",
        r"born\s*[:\-]\s*([^\n\r]+)",
    ])
    
    # Prefer the explicitly requested study/exam over the clinical indication.
    requested_study = _find_value(text, [
        r"(?:examination|exam|investigation|procedure|test)\s+(?:requested|required|details?)\s*[:\-]\s*([^\n\r]{5,})",
        r"requested?\s+(?:study|examination|imaging|scan)\s*[:\-]\s*([^\n\r]{5,})",
        r"requested\s+procedure\s*[:\-]\s*([^\n\r]{5,})",
        r"study\s+requested\s*[:\-]\s*([^\n\r]{5,})",
        r"scan\s+requested\s*[:\-]\s*([^\n\r]{5,})",
    ])

    study_description = requested_study or _find_value(text, [
        r"study\s+description\s*[:\-]\s*([^\n\r]{5,})",
        r"study\s*[:\-]\s*([^\n\r]{5,})",
    ])
    
    # Modality extraction - look for known modality keywords
    modality_raw = _find_value(text, [
        r"modality\s*[:\-]\s*([^\n\r]+)",
        r"(?:imaging\s+)?type\s*[:\-]\s*([^\n\r]+)",
        r"\b(ct|computed\s+tomography|mri|magnetic\s+resonance|ultrasound|us|x-?ray|xr|pet|dexa|dxa)\b",
    ])
    
    # Normalize modality
    normalized_modality = ""
    if modality_raw:
        normalized_modality = modality_raw.upper()
        # Map common aliases
        if "CT" in normalized_modality or "COMPUTED" in normalized_modality:
            normalized_modality = "CT"
        elif "MRI" in normalized_modality or "MAGNETIC" in normalized_modality:
            normalized_modality = "MRI"
        elif "XRAY" in normalized_modality or "X-RAY" in normalized_modality or modality_raw.upper() == "XR":
            normalized_modality = "XR"
        elif "US" in normalized_modality or "ULTRASOUND" in normalized_modality:
            normalized_modality = "ULTRASOUND"
        elif "PET" in normalized_modality:
            normalized_modality = "PET"
        elif "DEX" in normalized_modality or "DXA" in normalized_modality:
            normalized_modality = "DEXA"
        else:
            # Keep first word if no match
            normalized_modality = normalized_modality.split()[0] if normalized_modality else ""

    fields = {
        "patient_first_name": first_name,
        "patient_surname": surname,
        "patient_referral_id": patient_identifier,
        "patient_dob": dob,
        "study_description": study_description,
        "modality": normalized_modality,
        "admin_notes": "",
    }

    if not patient_identifier and referral_reference:
        warnings.append("Referral reference found, but no patient/NHS/hospital identifier was confidently extracted.")

    # Calculate confidence: presence of key required fields
    required_for_confidence = [
        fields["patient_first_name"],
        fields["patient_surname"],
        fields["patient_referral_id"],
        fields["study_description"],
    ]
    found_required = sum(1 for value in required_for_confidence if value)
    confidence = round(found_required / max(1, len(required_for_confidence)), 2)

    return {
        "text_preview": text[:2000],
        "warnings": warnings,
        "fields": fields,
        "confidence": confidence,
    }
