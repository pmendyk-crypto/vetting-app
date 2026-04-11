import unittest
from unittest.mock import patch

from app.main import (
    build_case_preview_context,
    can_use_uncatalogued_exam_exception,
    display_case_event_label,
    display_case_status,
    display_decision_label,
    format_exam_label,
    find_matching_exam_catalogue_item,
    get_exam_catalogue_review_summary,
    get_report_sent_summary,
    normalize_decision_label,
    resolve_case_exam_selection,
    should_allow_same_origin_frame,
)


class DisplayHelperTests(unittest.TestCase):
    def test_normalize_decision_label_maps_current_values(self):
        self.assertEqual(normalize_decision_label("approved"), "Approved")
        self.assertEqual(normalize_decision_label("Approved with Comment"), "Approved with Comment")
        self.assertEqual(normalize_decision_label("reject"), "Rejected")

    def test_display_decision_label_maps_legacy_values(self):
        self.assertEqual(display_decision_label("justified"), "Approved")
        self.assertEqual(display_decision_label("justified with comment"), "Approved with Comment")
        self.assertEqual(display_decision_label("not justified"), "Rejected")

    def test_display_decision_label_falls_back_to_status_display(self):
        self.assertEqual(display_decision_label("", fallback_status="vetted"), "Approved")
        self.assertEqual(display_decision_label(None, fallback_status="rejected"), "Rejected")

    def test_display_case_status_standardizes_vetted(self):
        self.assertEqual(display_case_status("vetted"), "Approved")
        self.assertEqual(display_case_status("reopened"), "Reopened")

    def test_display_case_event_label_humanizes_report_sent(self):
        self.assertEqual(display_case_event_label("REPORT_SENT"), "Justification Sent")
        self.assertEqual(display_case_event_label("REPORT_SENT_RESET"), "Justification Sent Reset")

    def test_format_exam_label_includes_study_code(self):
        self.assertEqual(format_exam_label("MRI Brain", "MRI001"), "MRI Brain (MRI001)")
        self.assertEqual(format_exam_label("MRI Brain", ""), "MRI Brain")

    def test_report_sent_summary_uses_timestamp(self):
        sent, label = get_report_sent_summary({"report_sent_at": "2026-04-09T09:15:00+00:00"})
        self.assertTrue(sent)
        self.assertIn("09/04/2026", label)

    def test_report_sent_summary_handles_missing_timestamp(self):
        sent, label = get_report_sent_summary({})
        self.assertFalse(sent)
        self.assertEqual(label, "")

    def test_exam_catalogue_review_summary_uses_reason(self):
        flagged, label = get_exam_catalogue_review_summary(
            {
                "exam_catalogue_requires_review": 1,
                "exam_catalogue_exception_reason": "Rare temporary exam",
                "exam_catalogue_exception_at": "2026-04-09T10:00:00+00:00",
                "exam_catalogue_exception_by": "owner",
            }
        )
        self.assertTrue(flagged)
        self.assertIn("Rare temporary exam", label)
        self.assertIn("owner", label)

    def test_uncatalogued_exam_exception_requires_superuser(self):
        self.assertTrue(can_use_uncatalogued_exam_exception({"is_superuser": 1}))
        self.assertFalse(can_use_uncatalogued_exam_exception({"is_superuser": 0}))

    def test_edit_flow_preserves_legacy_exam_when_unchanged(self):
        resolved = resolve_case_exam_selection(
            user={"is_superuser": 0},
            org_id=2,
            study_description="Legacy MRI Study",
            study_description_preset_id="",
            study_code="LEG-01",
            modality="MRI",
            existing_case={
                "study_description": "Legacy MRI Study",
                "study_code": "LEG-01",
                "modality": "MRI",
                "study_description_preset_id": None,
                "exam_catalogue_requires_review": 0,
            },
        )
        self.assertEqual(resolved["study_description"], "Legacy MRI Study")
        self.assertEqual(resolved["study_code"], "LEG-01")
        self.assertEqual(resolved["modality"], "MRI")

    def test_case_preview_context_uses_available_attachment_when_primary_missing(self):
        preview = build_case_preview_context(
            "CASE-1",
            {
                "uploaded_filename": "old.pdf",
                "stored_filepath": None,
                "attachment_previewable": False,
            },
            [
                {
                    "id": "att-1",
                    "uploaded_filename": "new.pdf",
                    "available": True,
                }
            ],
        )
        self.assertEqual(preview["preview_source"], "attachment")
        self.assertTrue(preview["preview_available"])
        self.assertIn("/attachments/att-1/preview", preview["preview_url"])

    def test_same_origin_frame_allows_case_attachment_preview_routes(self):
        self.assertTrue(should_allow_same_origin_frame("/case/ABC/attachments/1/preview"))
        self.assertTrue(should_allow_same_origin_frame("/case/ABC/attachments/1/inline"))
        self.assertTrue(should_allow_same_origin_frame("/submit/referral-trial/attachment/token/preview"))
        self.assertTrue(should_allow_same_origin_frame("/case/ABC/pdf", "1"))
        self.assertFalse(should_allow_same_origin_frame("/owner/exam-catalogue"))

    @patch("app.main.list_exam_catalogue")
    def test_find_matching_exam_catalogue_item_prefers_study_code_then_modality(self, mock_list_exam_catalogue):
        mock_list_exam_catalogue.return_value = [
            {"id": 10, "modality": "XR", "description": "CT Abdomen", "study_code": "CABDO"},
            {"id": 11, "modality": "CT", "description": "CT Abdomen", "study_code": "CABDO"},
        ]
        match = find_matching_exam_catalogue_item(
            org_id=2,
            study_description="CT Abdomen",
            modality="CT",
            study_code="cabdo",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], 11)


if __name__ == "__main__":
    unittest.main()
