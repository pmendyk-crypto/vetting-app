from __future__ import annotations

from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from io import BytesIO
from pathlib import Path
import importlib
import re
import tempfile


SUPPORTED_REFERRAL_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".csv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
}

REFERRAL_ATTACHMENT_PREFERENCE = {
    ".pdf": 0,
    ".docx": 1,
    ".txt": 2,
    ".md": 3,
    ".html": 4,
    ".htm": 4,
    ".csv": 5,
    ".json": 6,
    ".xml": 7,
    ".png": 8,
    ".jpg": 8,
    ".jpeg": 8,
    ".tif": 8,
    ".tiff": 8,
    ".bmp": 8,
    ".gif": 8,
}


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def _strip_html(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _decode_email_part(part) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw_payload = part.get_payload()
        if isinstance(raw_payload, str):
            return raw_payload
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _extract_email_body(message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.is_multipart() or part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type == "text/plain":
                plain_parts.append(_decode_email_part(part))
            elif content_type == "text/html":
                html_parts.append(_strip_html(_decode_email_part(part)))
    else:
        content_type = message.get_content_type()
        if content_type == "text/html":
            html_parts.append(_strip_html(_decode_email_part(message)))
        else:
            plain_parts.append(_decode_email_part(message))
    body = "\n\n".join(part.strip() for part in plain_parts if part and part.strip())
    if body:
        return body
    return "\n\n".join(part.strip() for part in html_parts if part and part.strip())


def _parse_email_contact(value: str | None) -> tuple[str, str]:
    addresses = getaddresses([value or ""])
    for name, address in addresses:
        cleaned_address = (address or "").strip().lower()
        if cleaned_address:
            return " ".join((name or "").replace('"', "").split()), cleaned_address
    return "", ""


def _parse_email_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return ""
    if not parsed:
        return ""
    return parsed.date().isoformat()


def _coerce_email_date(value) -> str:
    if not value:
        return ""
    if hasattr(value, "date"):
        try:
            return value.date().isoformat()
        except Exception:
            pass
    text_value = str(value or "").strip()
    if not text_value:
        return ""
    parsed = _parse_email_date(text_value)
    if parsed:
        return parsed
    try:
        return text_value[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text_value) else ""
    except Exception:
        return ""


def _organisation_from_email(email_address: str) -> str:
    domain = (email_address or "").split("@")[-1].lower()
    if not domain or "." not in domain:
        return ""
    first_label = domain.split(".", 1)[0]
    generic_labels = {"gmail", "hotmail", "icloud", "live", "me", "nhs", "outlook", "yahoo"}
    if first_label in generic_labels:
        return ""
    return " ".join(part.capitalize() for part in re.split(r"[-_.]+", first_label) if part)


def _email_attachments(message) -> list[dict]:
    attachments: list[dict] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if not filename and part.get_content_disposition() != "attachment":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        safe_filename = Path(filename or "email_attachment.bin").name
        attachments.append(
            {
                "filename": safe_filename,
                "content_type": part.get_content_type(),
                "bytes": payload,
            }
        )
    return attachments


def _select_referral_email_attachment(attachments: list[dict]) -> dict | None:
    candidates = []
    for attachment in attachments:
        ext = Path(attachment.get("filename") or "").suffix.lower()
        if ext in SUPPORTED_REFERRAL_EXTENSIONS:
            candidates.append(attachment)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            REFERRAL_ATTACHMENT_PREFERENCE.get(Path(item.get("filename") or "").suffix.lower(), 99),
            str(item.get("filename") or "").lower(),
        ),
    )[0]


def _parse_email_import_payload(
    *,
    filename: str,
    data: bytes,
    subject: str,
    from_name: str,
    from_email: str,
    reply_name: str = "",
    reply_email: str = "",
    sent_date: str = "",
    body_text: str = "",
    attachments: list[dict] | None = None,
    source_type: str = "email",
    source_format: str = "",
) -> dict:
    warnings: list[str] = []
    attachments = attachments or []
    requestor_name = reply_name or from_name
    requestor_email = reply_email or from_email
    selected_attachment = _select_referral_email_attachment(attachments)

    if selected_attachment:
        attachment_filename = selected_attachment["filename"]
        attachment_bytes = selected_attachment["bytes"]
        parsed = parse_referral_attachment(attachment_filename, attachment_bytes)
        warnings.extend(parsed.get("warnings") or [])
        warnings.append(f"Imported email attachment: {attachment_filename}")
        primary_attachment = {
            "filename": attachment_filename,
            "bytes": attachment_bytes,
            "source": "email_attachment",
        }
        text_preview = parsed.get("text_preview", "")
    else:
        warnings.append("No supported referral attachment was found in the email. The email body was used instead.")
        parsed = _parse_referral_text(body_text, [])
        body_filename = f"{Path(filename or 'email').stem or 'email'}_body.txt"
        primary_attachment = {
            "filename": body_filename,
            "bytes": body_text.encode("utf-8"),
            "source": "email_body",
        }
        text_preview = body_text[:2000]

    fields = dict(parsed.get("fields") or {})
    referring_clinician = _find_value(body_text, [r"referring\s+clinician\s*[:\-]\s*([^\n\r]+)"])
    practice_name = _find_value(body_text, [
        r"(?:practice|organisation|organization|site|department)\s*[:\-]\s*([^\n\r]+)",
    ])

    fields["request_date"] = sent_date or fields.get("request_date", "")
    fields["requestor_name"] = requestor_name or referring_clinician or ""
    fields["requestor_email"] = requestor_email or ""
    fields["requestor_organisation"] = practice_name or _organisation_from_email(requestor_email)
    fields["requestor_reference"] = subject
    fields["send_report_to_requestor"] = "1" if requestor_email else ""

    source = {
        "type": source_type,
        "format": source_format,
        "subject": subject,
        "from_name": from_name,
        "from_email": from_email,
        "reply_to_name": reply_name,
        "reply_to_email": reply_email,
        "requestor_name": fields["requestor_name"],
        "requestor_email": fields["requestor_email"],
        "sent_date": sent_date,
        "attachment_count": len(attachments),
        "selected_attachment": selected_attachment["filename"] if selected_attachment else "",
    }

    return {
        "text_preview": text_preview,
        "warnings": warnings,
        "fields": fields,
        "confidence": parsed.get("confidence", 0),
        "source": source,
        "primary_attachment": primary_attachment,
        "source_email": {
            "filename": Path(filename or "referral_email").name,
            "bytes": data,
        },
    }


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


def _parse_referral_text(text: str, warnings: list[str] | None = None) -> dict:
    warnings = list(warnings or [])
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


def parse_email_referral_attachment(filename: str, data: bytes) -> dict:
    try:
        message = BytesParser(policy=policy.default).parsebytes(data)
    except Exception:
        return _parse_referral_text(
            _decode_text(data),
            ["Email file could not be parsed reliably. The raw message text was used instead."],
        )

    subject = str(message.get("subject") or "").strip()
    reply_name, reply_email = _parse_email_contact(message.get("reply-to"))
    from_name, from_email = _parse_email_contact(message.get("from"))
    requestor_name = reply_name or from_name
    requestor_email = reply_email or from_email
    sent_date = _parse_email_date(message.get("date"))
    body_text = _extract_email_body(message)
    attachments = _email_attachments(message)
    return _parse_email_import_payload(
        filename=filename or "referral_email.eml",
        data=data,
        subject=subject,
        from_name=from_name,
        from_email=from_email,
        reply_name=reply_name,
        reply_email=reply_email,
        sent_date=sent_date,
        body_text=body_text,
        attachments=attachments,
        source_type="email",
        source_format="eml",
    )


def _msg_attachment_filename(attachment) -> str:
    for attr in ("longFilename", "shortFilename", "name", "filename"):
        value = getattr(attachment, attr, None)
        if value:
            return Path(str(value)).name
    return "msg_attachment.bin"


def _msg_attachment_bytes(attachment) -> bytes:
    data_value = getattr(attachment, "data", None)
    if isinstance(data_value, bytes):
        return data_value
    if isinstance(data_value, str):
        return data_value.encode("utf-8")
    for attr in ("getData", "get_data"):
        method = getattr(attachment, attr, None)
        if callable(method):
            result = method()
            if isinstance(result, bytes):
                return result
            if isinstance(result, str):
                return result.encode("utf-8")
    return b""


def parse_msg_referral_attachment(filename: str, data: bytes) -> dict:
    try:
        extract_msg = importlib.import_module("extract_msg")
    except Exception:
        return _parse_referral_text(
            "",
            ["Outlook .msg import requires the extract-msg package. Upload an .eml file or the referral attachment directly."],
        )

    temp_path = None
    msg = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".msg") as temp_file:
            temp_file.write(data)
            temp_path = temp_file.name
        msg = extract_msg.Message(temp_path)
        subject = str(getattr(msg, "subject", "") or "").strip()
        from_name, from_email = _parse_email_contact(
            str(
                getattr(msg, "sender", "")
                or getattr(msg, "senderEmail", "")
                or getattr(msg, "sender_email", "")
                or ""
            )
        )
        if not from_email:
            sender_email = str(getattr(msg, "senderEmail", "") or getattr(msg, "sender_email", "") or "").strip().lower()
            sender_name = str(getattr(msg, "sender", "") or "").strip()
            from_name, from_email = sender_name, sender_email
        sent_date = _coerce_email_date(
            getattr(msg, "date", None)
            or getattr(msg, "parsedDate", None)
            or getattr(msg, "messageDeliveryTime", None)
        )
        body_text = str(getattr(msg, "body", "") or "")
        if not body_text.strip():
            html_body = getattr(msg, "htmlBody", "") or getattr(msg, "html_body", "")
            if isinstance(html_body, bytes):
                html_body = html_body.decode("utf-8", errors="replace")
            body_text = _strip_html(str(html_body or ""))
        attachments = []
        for attachment in getattr(msg, "attachments", []) or []:
            payload = _msg_attachment_bytes(attachment)
            if not payload:
                continue
            attachment_filename = _msg_attachment_filename(attachment)
            attachments.append(
                {
                    "filename": attachment_filename,
                    "content_type": mimetype_from_filename(attachment_filename),
                    "bytes": payload,
                }
            )
        return _parse_email_import_payload(
            filename=filename or "referral_email.msg",
            data=data,
            subject=subject,
            from_name=from_name,
            from_email=from_email,
            sent_date=sent_date,
            body_text=body_text,
            attachments=attachments,
            source_type="email",
            source_format="msg",
        )
    except Exception as exc:
        return _parse_referral_text("", [f"Outlook .msg import failed: {exc}"])
    finally:
        try:
            if msg and hasattr(msg, "close"):
                msg.close()
        except Exception:
            pass
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass


def mimetype_from_filename(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    mapping = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".html": "text/html",
        ".htm": "text/html",
        ".csv": "text/csv",
        ".json": "application/json",
        ".xml": "application/xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    return mapping.get(ext, "application/octet-stream")


def parse_referral_attachment(filename: str, data: bytes) -> dict:
    ext = Path(filename or "").suffix.lower()
    if ext == ".eml":
        return parse_email_referral_attachment(filename, data)
    if ext == ".msg":
        return parse_msg_referral_attachment(filename, data)

    text, warnings = extract_referral_text(filename, data)
    return _parse_referral_text(text, warnings)
