from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepInFrame,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output" / "pdf"
OUTPUT_PATH = OUTPUT_DIR / "app-summary-one-page.pdf"


def bullet_list(items: list[str], style: ParagraphStyle) -> list[Paragraph]:
    return [Paragraph(f"• {item}", style) for item in items]


def build_pdf() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#17324d"),
        spaceAfter=4,
    )
    subtitle = ParagraphStyle(
        "Subtitle",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#5b6b7d"),
        spaceAfter=10,
    )
    h2 = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#17324d"),
        spaceBefore=0,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8.4,
        leading=11,
        textColor=colors.HexColor("#22313f"),
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    bullet = ParagraphStyle(
        "Bullet",
        parent=body,
        leftIndent=0,
        firstLineIndent=0,
        bulletIndent=0,
        spaceAfter=2.5,
    )
    footer = ParagraphStyle(
        "Footer",
        parent=body,
        fontSize=7.6,
        leading=9,
        textColor=colors.HexColor("#6c7a89"),
        spaceAfter=0,
    )

    left_flow = [
        Paragraph("What It Is", h2),
        Paragraph(
            "RadFlow is a FastAPI-based web app for managing imaging referral vetting workflows across organisations. "
            "It handles case intake, assignment, radiologist decisions, and downloadable audit outputs from a single server-side application.",
            body,
        ),
        Paragraph("Who It's For", h2),
        Paragraph(
            "Primary users appear to be imaging admins and radiologists working within organisation-scoped workflows; "
            "the repo also includes owner/superuser controls for managing multiple organisations.",
            body,
        ),
        Paragraph("How To Run", h2),
        *bullet_list(
            [
                "Activate the repo virtual environment: `.venv\\Scripts\\Activate.ps1`.",
                "Create local settings once: `Copy-Item .env.local.example .env.local`.",
                "Start locally with `./scripts/run-local.ps1`.",
                "Open `http://127.0.0.1:8000`.",
            ],
            bullet,
        ),
    ]

    right_flow = [
        Paragraph("What It Does", h2),
        *bullet_list(
            [
                "Supports login, session handling, password reset, rate limiting, and account lockout logic.",
                "Lets admins submit cases with patient, institution, study, attachment, and notes data.",
                "Includes a referral trial parser that extracts fields from PDF, DOCX, text, and image uploads.",
                "Assigns cases to radiologists and gives radiologists a dedicated vetting workflow.",
                "Stores protocol and study-description presets, including study-to-protocol lookups.",
                "Records case timeline events and exports admin data as CSV and case timelines as PDF or CSV.",
                "Scopes data by organisation, with owner dashboards for multi-tenant management.",
            ],
            bullet,
        ),
        Paragraph("How It Works", h2),
        Paragraph(
            "Server: one main FastAPI app (`app/main.py`) renders Jinja2 templates and serves static assets. "
            "State and auth: session middleware manages signed sessions; role checks route users to owner, admin, or radiologist screens. "
            "Data: the app uses SQLite by default via `DB_PATH`, or PostgreSQL when `DATABASE_URL` is set; schema evidence shows tables for organisations, users, memberships, cases, institutions, protocols, case events, password reset tokens, and study-description presets. "
            "Files: uploads are written under `UPLOAD_DIR` unless Azure Blob Storage is enabled. "
            "Flow: intake or referral parsing creates case records and attachments, admins review/assign, radiologists vet with decision and protocol data, then the app persists status updates and timeline events and can generate case PDFs/CSVs.",
            body,
        ),
        Spacer(1, 3),
        Paragraph(
            "Not found in repo: a separate frontend app, background job system, or external message queue.",
            footer,
        ),
    ]

    left_box = KeepInFrame(78 * mm, 235 * mm, left_flow, mode="shrink")
    right_box = KeepInFrame(104 * mm, 235 * mm, right_flow, mode="shrink")

    story = [
        Paragraph("Vetting App Summary", title),
        Paragraph(
            "One-page repo-backed overview generated from source code, scripts, environment templates, and migrations.",
            subtitle,
        ),
        Table(
            [[left_box, right_box]],
            colWidths=[80 * mm, 106 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#d7dee7")),
                    ("LINEBEFORE", (1, 0), (1, 0), 0.6, colors.HexColor("#d7dee7")),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ]
            ),
        ),
    ]

    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Vetting App Summary",
        author="Codex",
    )
    doc.build(story)

    reader = PdfReader(str(OUTPUT_PATH))
    if len(reader.pages) != 1:
        raise RuntimeError(f"Expected a single-page PDF, found {len(reader.pages)} pages")


if __name__ == "__main__":
    build_pdf()
    print(OUTPUT_PATH)
