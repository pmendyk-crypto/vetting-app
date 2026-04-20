from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone
import sys
import types
from unittest.mock import patch

from app.referral_ingest import parse_referral_attachment


def test_eml_import_prefills_requestor_and_parses_referral_attachment():
    message = EmailMessage()
    message["From"] = "Dr Sarah Johnson <referrals@centralmed.co.uk>"
    message["Reply-To"] = "Referral Team <referrals@centralmed.co.uk>"
    message["To"] = "intake@example.org"
    message["Subject"] = "Referral GP-2026-03-0412"
    message["Date"] = format_datetime(datetime(2026, 3, 4, 10, 30, tzinfo=timezone.utc))
    message.set_content(
        "Please find the attached referral.\n\n"
        "Practice: Central Medical Centre\n"
        "Referring Clinician: Dr Sarah Johnson\n"
    )
    referral_text = (
        "Patient Name: John Smith\n"
        "Date of Birth: 15/06/1978\n"
        "NHS Number: 123 456 7890\n"
        "Requested Study: MRI Scan - Lumbar Spine\n"
        "Modality: MRI\n"
    )
    message.add_attachment(
        referral_text.encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename="referral.txt",
    )

    parsed = parse_referral_attachment("incoming_referral.eml", message.as_bytes())

    assert parsed["source"]["type"] == "email"
    assert parsed["source"]["format"] == "eml"
    assert parsed["source"]["selected_attachment"] == "referral.txt"
    assert parsed["primary_attachment"]["filename"] == "referral.txt"
    assert parsed["source_email"]["filename"] == "incoming_referral.eml"
    assert parsed["fields"]["patient_first_name"] == "John"
    assert parsed["fields"]["patient_surname"] == "Smith"
    assert parsed["fields"]["patient_referral_id"] == "123 456 7890"
    assert parsed["fields"]["requestor_name"] == "Referral Team"
    assert parsed["fields"]["requestor_email"] == "referrals@centralmed.co.uk"
    assert parsed["fields"]["requestor_organisation"] == "Central Medical Centre"
    assert parsed["fields"]["requestor_reference"] == "Referral GP-2026-03-0412"
    assert parsed["fields"]["request_date"] == "2026-03-04"
    assert parsed["fields"]["send_report_to_requestor"] == "1"


def test_msg_import_prefills_requestor_and_parses_referral_attachment():
    class FakeAttachment:
        longFilename = "referral.txt"
        data = (
            "Patient Name: John Smith\n"
            "Date of Birth: 15/06/1978\n"
            "NHS Number: 123 456 7890\n"
            "Requested Study: MRI Scan - Lumbar Spine\n"
            "Modality: MRI\n"
        ).encode("utf-8")

    class FakeMessage:
        def __init__(self, path):
            self.path = path
            self.subject = "Referral GP-2026-03-0412"
            self.sender = "Referral Team <referrals@centralmed.co.uk>"
            self.date = datetime(2026, 3, 4, 10, 30, tzinfo=timezone.utc)
            self.body = (
                "Please find the attached referral.\n\n"
                "Practice: Central Medical Centre\n"
                "Referring Clinician: Dr Sarah Johnson\n"
            )
            self.attachments = [FakeAttachment()]
            self.closed = False

        def close(self):
            self.closed = True

    fake_extract_msg = types.SimpleNamespace(Message=FakeMessage)

    with patch.dict(sys.modules, {"extract_msg": fake_extract_msg}):
        parsed = parse_referral_attachment("incoming_referral.msg", b"fake msg bytes")

    assert parsed["source"]["type"] == "email"
    assert parsed["source"]["format"] == "msg"
    assert parsed["source"]["selected_attachment"] == "referral.txt"
    assert parsed["primary_attachment"]["filename"] == "referral.txt"
    assert parsed["source_email"]["filename"] == "incoming_referral.msg"
    assert parsed["fields"]["patient_first_name"] == "John"
    assert parsed["fields"]["patient_surname"] == "Smith"
    assert parsed["fields"]["patient_referral_id"] == "123 456 7890"
    assert parsed["fields"]["requestor_name"] == "Referral Team"
    assert parsed["fields"]["requestor_email"] == "referrals@centralmed.co.uk"
    assert parsed["fields"]["requestor_organisation"] == "Central Medical Centre"
    assert parsed["fields"]["requestor_reference"] == "Referral GP-2026-03-0412"
    assert parsed["fields"]["request_date"] == "2026-03-04"
    assert parsed["fields"]["send_report_to_requestor"] == "1"
