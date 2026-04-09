from app.main import (
    ensure_default_study_description_presets,
    ensure_exam_catalogue_assignment_schema,
    ensure_report_sent_schema,
)


def main() -> None:
    ensure_exam_catalogue_assignment_schema()
    ensure_report_sent_schema()
    ensure_default_study_description_presets()
    print("Exam catalogue and report-sent backfill completed successfully.")


if __name__ == "__main__":
    main()
