#!/usr/bin/env python3
"""Build the offline demo execution and screenshot evidence report."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

if __package__:
    from .report_diagrams import DIAGRAMS
else:
    from report_diagrams import DIAGRAMS

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "output" / "playwright"
OUT = ROOT / "output" / "pdf" / "m365-risk-offline-demo-evidence-report.pdf"
TMP = ROOT / "tmp" / "pdfs"
MODEL = ROOT / "artifacts" / "models" / "current"

PAGE_W, PAGE_H = landscape(A4)
INK = colors.HexColor("#11261f")
MUTED = colors.HexColor("#52645d")
GREEN = colors.HexColor("#087f5b")
GREEN_DARK = colors.HexColor("#07543f")
MINT = colors.HexColor("#dff6ec")
PALE = colors.HexColor("#f4f8f6")
AMBER = colors.HexColor("#b36b00")
RED = colors.HexColor("#b42318")
LINE = colors.HexColor("#cddbd5")


def register_fonts() -> tuple[str, str]:
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
    ]
    bold_candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/Library/Fonts/Arial Bold.ttf"),
    ]
    regular = next((p for p in candidates if p.exists()), None)
    bold = next((p for p in bold_candidates if p.exists()), None)
    if regular and bold:
        pdfmetrics.registerFont(TTFont("EvidenceSans", str(regular)))
        pdfmetrics.registerFont(TTFont("EvidenceSansBold", str(bold)))
        return "EvidenceSans", "EvidenceSansBold"
    return "Helvetica", "Helvetica-Bold"


FONT, FONT_BOLD = register_fonts()
styles = getSampleStyleSheet()
styles.add(
    ParagraphStyle(
        "ReportTitle",
        fontName=FONT_BOLD,
        fontSize=29,
        leading=34,
        textColor=INK,
        alignment=TA_LEFT,
        spaceAfter=8,
    )
)
styles.add(
    ParagraphStyle(
        "Subtitle",
        fontName=FONT,
        fontSize=13,
        leading=19,
        textColor=MUTED,
        spaceAfter=10,
    )
)
styles.add(
    ParagraphStyle(
        "Section",
        fontName=FONT_BOLD,
        fontSize=18,
        leading=22,
        textColor=GREEN_DARK,
        spaceAfter=8,
    )
)
styles.add(
    ParagraphStyle(
        "BodyEvidence",
        fontName=FONT,
        fontSize=9.2,
        leading=13,
        textColor=INK,
        spaceAfter=6,
    )
)
styles.add(
    ParagraphStyle(
        "SmallEvidence",
        fontName=FONT,
        fontSize=7.5,
        leading=10,
        textColor=MUTED,
    )
)
styles.add(
    ParagraphStyle(
        "CaptionEvidence",
        fontName=FONT,
        fontSize=7.2,
        leading=9,
        textColor=MUTED,
        alignment=TA_CENTER,
        spaceBefore=4,
    )
)
styles.add(
    ParagraphStyle(
        "Callout",
        fontName=FONT_BOLD,
        fontSize=11,
        leading=15,
        textColor=GREEN_DARK,
        alignment=TA_CENTER,
    )
)
styles.add(
    ParagraphStyle(
        "TableHeader",
        fontName=FONT_BOLD,
        fontSize=7.4,
        leading=9,
        textColor=colors.white,
    )
)
styles.add(
    ParagraphStyle(
        "TableCell",
        fontName=FONT,
        fontSize=7.2,
        leading=9,
        textColor=INK,
    )
)


def p(text: str, style: str = "BodyEvidence") -> Paragraph:
    return Paragraph(text, styles[style])


def screenshot(path: Path, max_w: float, max_h: float) -> Image:
    with PILImage.open(path) as im:
        width, height = im.size
    scale = min(max_w / width, max_h / height)
    return Image(str(path), width=width * scale, height=height * scale)


def crop_top(source: Path, destination: Path, height: int = 620) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with PILImage.open(source) as im:
        cropped = im.crop((0, 0, im.width, min(height, im.height)))
        cropped.save(destination, optimize=True)
    return destination


def image_cell(path: Path, caption: str, width: float, height: float) -> list:
    return [
        screenshot(path, width, height),
        p(caption, "CaptionEvidence"),
    ]


def diagram_flowable(factory):
    drawing = factory()
    scale = 0.86
    drawing.scale(scale, scale)
    drawing.width *= scale
    drawing.height *= scale
    drawing.hAlign = "CENTER"
    return drawing


def evidence_table(rows: list[list[str]], widths: list[float]) -> Table:
    converted = []
    for i, row in enumerate(rows):
        style = "TableHeader" if i == 0 else "TableCell"
        converted.append([p(str(cell), style) for cell in row])
    table = Table(converted, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), GREEN_DARK),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def pair_page(story: list, title: str, left: tuple[str, str], right: tuple[str, str]) -> None:
    story.extend([PageBreak(), p(title, "Section")])
    content_w = PAGE_W - 30 * mm
    col_w = (content_w - 6 * mm) / 2
    table = Table(
        [[
            image_cell(SHOTS / left[0], left[1], col_w - 4 * mm, 410),
            image_cell(SHOTS / right[0], right[1], col_w - 4 * mm, 410),
        ]],
        colWidths=[col_w, col_w],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)


def page_decor(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(GREEN_DARK)
    canvas.rect(0, PAGE_H - 7 * mm, PAGE_W, 7 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(LINE)
    canvas.line(15 * mm, 11 * mm, PAGE_W - 15 * mm, 11 * mm)
    canvas.setFont(FONT, 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(15 * mm, 6.5 * mm, "M365 Risk Platform - Offline execution evidence - 2026-07-28")
    canvas.drawRightString(PAGE_W - 15 * mm, 6.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    incoming_crop = crop_top(SHOTS / "03-incoming-mail-stream.png", TMP / "03-incoming-crop.png")
    pause_crop = crop_top(SHOTS / "04-paused-stream.png", TMP / "04-paused-crop.png")
    with (MODEL / "metrics.json").open() as handle:
        metrics = json.load(handle)
    selected = metrics["selected"]
    user_risk = metrics["user_risk"]

    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=15 * mm,
        title="M365 Risk Platform Architecture and Offline Demo Evidence Report",
        author="M365 Risk Platform",
        subject="Architecture, UML, runtime, scenario, incoming mail, model and test evidence",
    )
    story: list = []

    # Cover
    story.extend(
        [
            Spacer(1, 18 * mm),
            p("OFFLINE-FIRST SECURITY ANALYTICS", "Callout"),
            Spacer(1, 8 * mm),
            p("M365 User Risk Platform", "ReportTitle"),
            p("Architecture, UML, execution, incoming-mail simulation, scenario testing, and visual evidence report", "Subtitle"),
            Spacer(1, 4 * mm),
            Table(
                [[
                    p("RUNNING", "Callout"),
                    p("E2E PASSED", "Callout"),
                    p("12 DIAGRAMS + 14 CAPTURES", "Callout"),
                    p("OFFLINE AND TENANT-SAFE", "Callout"),
                ]],
                colWidths=[46 * mm] * 4,
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), MINT),
                        ("BOX", (0, 0), (-1, -1), 0.7, GREEN),
                        ("INNERGRID", (0, 0), (-1, -1), 0.5, GREEN),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("TOPPADDING", (0, 0), (-1, -1), 10),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ]
                ),
            ),
            Spacer(1, 12 * mm),
            p(
                "The production-minded monorepo was started locally with PostgreSQL, FastAPI, the durable worker, "
                "mock Microsoft Graph/OIDC services, and the Next.js dashboard. The evidence below records the "
                "actual live behavior on the target Apple Silicon Mac without company M365 access.",
                "Subtitle",
            ),
            Spacer(1, 6 * mm),
            evidence_table(
                [
                    ["Artifact", "Location / result"],
                    ["Dashboard", "http://localhost:3000 - running"],
                    ["API documentation", "http://localhost:8000/docs - healthy"],
                    ["Installed release", "0.1.0-demo-j - checksums, SBOMs, migration, backup, and smoke verified"],
                    ["Evidence screenshots", "output/playwright/ - 14 PNG captures"],
                    ["Generated report", "output/pdf/m365-risk-offline-demo-evidence-report.pdf"],
                ],
                [50 * mm, 145 * mm],
            ),
            Spacer(1, 9 * mm),
            p("Prepared 28 July 2026 - Africa/Tunis", "SmallEvidence"),
        ]
    )

    # Executive evidence summary
    story.extend(
        [
            PageBreak(),
            p("1. Verified execution summary", "Section"),
            p(
                "The offline demo is a real multi-service execution, not a static mockup. The worker consumes "
                "Graph-compatible delta pages from a local simulator, persists tenant-scoped metadata and daily "
                "features in PostgreSQL, computes version-tagged risk scores, and exposes the results through the API and dashboard.",
            ),
            evidence_table(
                [
                    ["Area", "Executed evidence", "Result"],
                    ["Runtime", "API, worker, web, mock Graph/OIDC, PostgreSQL", "All services running; API and database healthy"],
                    ["Seeded demo", "2 tenants x 100 users x 90 days", "200 users and 18,000 tenant-scoped daily feature rows"],
                    ["Incoming mail", "Deterministic continuous metadata stream (2-second default)", "Live event counter changed in-browser; pause held the stream"],
                    ["Scenarios", "Normal, phishing, spoofing, impersonation, takeover, MFA, Entra, throttle, recovery", "All controls executed and captured"],
                    ["Isolation", "Signed mock OIDC tenant switch", "Contoso session showed an independent risk state"],
                    ["Browser E2E", "Login, reset, live arrival, phishing increase, explanation, feedback, recovery, tenant switch", "1 passed in 22.7 seconds; attack assertion remained <= 10 seconds"],
                    ["Unit / integration", "Python unit and PostgreSQL integration suites", "51 unit tests at 71.21% coverage and 6 integration tests passed"],
                    ["Performance", "Local read API, metadata throughput, and Compose memory", "p95 6.75 ms; 4,718.3 events/minute; 465.86 MiB"],
                    ["Security", "pip-audit, pnpm audit, and Trivy on final runtime images", "No known dependency issues and zero fixable high/critical image findings"],
                    ["Datasets", "Header-only SpamAssassin and Enron preparation", "6,047 labeled + 517,401 normal-behavior records"],
                ],
                [34 * mm, 100 * mm, 62 * mm],
            ),
            Spacer(1, 5 * mm),
            Table(
                [[p("Privacy invariant", "Callout"), p(
                    "Only header-derived metadata is processed and persisted. Subject, body, preview, unique body text, and attachment bytes are excluded.",
                    "BodyEvidence",
                )]],
                colWidths=[42 * mm, 154 * mm],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), MINT),
                        ("BOX", (0, 0), (-1, -1), 0.6, GREEN),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 7),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                ),
            ),
        ]
    )

    # Architecture and UML portfolio
    story.extend(
        [
            PageBreak(),
            p("Architecture and design diagram portfolio", "Section"),
            p(
                "These views form a defense-ready architecture pack for an end-of-study internship. "
                "They connect business actors and use cases to runtime components, deployment, security boundaries, "
                "data ownership, model governance, and delivery operations.",
            ),
            evidence_table(
                [
                    ["Diagram", "Notation / purpose"],
                    *[
                        [title, subtitle]
                        for title, subtitle, _factory, _note in DIAGRAMS
                    ],
                ],
                [70 * mm, 126 * mm],
            ),
            Spacer(1, 5 * mm),
            p(
                "Reading order: start with context and use cases, descend into containers and deployment, "
                "follow the operational sequences and privacy/data model, then close with ML governance and CI/CD.",
                "Callout",
            ),
        ]
    )
    for title, subtitle, factory, note in DIAGRAMS:
        story.extend(
            [
                PageBreak(),
                p(title, "Section"),
                p(subtitle, "BodyEvidence"),
                diagram_flowable(factory),
                Spacer(1, 2 * mm),
                Table(
                    [[p("Defense note", "Callout"), p(note, "BodyEvidence")]],
                    colWidths=[34 * mm, 162 * mm],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), PALE),
                            ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 7),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ]
                    ),
                ),
            ]
        )

    pair_page(
        story,
        "2. Signed offline login and normal dashboard",
        ("01-login.png", "Signed local OIDC login with explicit tenant and role selection."),
        ("02-normal-dashboard.png", "Normal tenant dashboard after reset: KPIs, risk distribution, users, health, freshness, model, and controls."),
    )

    # Incoming stream evidence
    story.extend([PageBreak(), p("3. Continuous incoming mail and pause behavior", "Section")])
    content_w = PAGE_W - 30 * mm
    col_w = (content_w - 6 * mm) / 2
    incoming_table = Table(
        [[
            image_cell(incoming_crop, "Live stream capture: normal traffic counter advanced from 1,081 to 1,084 in four seconds.", col_w - 4 * mm, 270),
            image_cell(pause_crop, "Paused capture: simulator status changed to Paused and the event total held for inspection.", col_w - 4 * mm, 270),
        ]],
        colWidths=[col_w, col_w],
        style=TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        ),
    )
    story.extend(
        [
            incoming_table,
            Spacer(1, 5 * mm),
            evidence_table(
                [
                    ["Check", "Observed behavior", "Acceptance"],
                    ["Continuous arrival", "Counter changed without a manual sync action", "Pass"],
                    ["Deterministic control", "Pause stopped generation and exposed an explicit Paused state", "Pass"],
                    ["Data minimization", "UI and persistence use sender/domain/routing/security features only", "Pass"],
                    ["Freshness", "Dashboard polling and worker recomputation expose new risk evidence", "Pass"],
                ],
                [42 * mm, 119 * mm, 35 * mm],
            ),
        ]
    )

    # Scenario matrix
    story.extend(
        [
            PageBreak(),
            p("4. Scenario execution matrix", "Section"),
            p(
                "Each simulator action was started through the dashboard using an idempotent scenario request. "
                "The worker consumed the resulting delta events and recomputed the selected user's score and factors.",
            ),
            evidence_table(
                [
                    ["Scenario", "Injected signal", "Observed dashboard outcome"],
                    ["Credential phishing", "Malicious header and routing pattern", "User 001 increased from 12 to 64; high-risk headers +34.3, behavior +20, privilege +10"],
                    ["Domain spoofing", "Look-alike / sender authentication anomaly", "Scenario became active and changed risk evidence; captured"],
                    ["Executive impersonation", "High-value display/sender relationship anomaly", "Selected user score reached 65; captured"],
                    ["Account takeover", "Behavioral compromise window", "Selected user score reached 85; captured"],
                    ["MFA removal", "Registration detail downgrade", "Selected user score reached 100; captured"],
                    ["Entra risk escalation", "Risky-user signal", "Entra scenario status and risk factors displayed; captured"],
                    ["Throttling", "Graph-compatible HTTP 429 / Retry-After", "Throttle state displayed while the retry-capable connector remained operational"],
                    ["Recovery", "Normal traffic and healthy connector state", "Scenario returned to normal; historical mail evidence remained explainable"],
                    ["Reset", "Deterministic seeded baseline", "Clean normal state restored for repeatable E2E execution"],
                ],
                [45 * mm, 73 * mm, 78 * mm],
            ),
            Spacer(1, 6 * mm),
            p(
                "The browser E2E suite independently asserts that the phishing score becomes greater than the clean baseline within the 10-second requirement after initial synchronization completes.",
                "Callout",
            ),
        ]
    )

    pair_page(
        story,
        "5. Email attack behaviors",
        ("05-credential-phishing.png", "Credential phishing: failed SPF/DKIM/DMARC, pseudonymous header telemetry, high-risk probabilities, and score factors visible."),
        ("06-domain-spoofing.png", "Domain spoofing: simulator status and resulting user risk evidence."),
    )
    pair_page(
        story,
        "6. Impersonation and account compromise",
        ("07-executive-impersonation.png", "Executive impersonation: communication and privilege signals combined."),
        ("08-account-takeover.png", "Account takeover: high-risk behavioral compromise result."),
    )
    pair_page(
        story,
        "7. Identity protection behaviors",
        ("09-mfa-removal.png", "MFA removal: registration downgrade produced a critical user score."),
        ("10-entra-escalation.png", "Entra escalation: risky-user signal incorporated into the hybrid score."),
    )
    pair_page(
        story,
        "8. Connector resilience and recovery",
        ("11-throttling.png", "Throttling: Graph-compatible failure control visible while retries are supported."),
        ("12-recovery.png", "Recovery: connector returned to normal while prior risk remained auditable."),
    )
    pair_page(
        story,
        "9. Analyst workflow and strict tenant isolation",
        ("13-feedback-and-explanation.png", "Analyst workflow: contributing factors, recommendation, note, and true-positive feedback recorded."),
        ("14-tenant-isolation.png", "Contoso tenant session: independent data state after signed logout/login switch."),
    )

    # Model and notebook evidence
    story.extend([PageBreak(), p("10. Model, notebook, and promotion evidence", "Section")])
    chart_w = 82 * mm
    charts = Table(
        [[
            image_cell(MODEL / "model_comparison.png", "Rules, logistic regression, and histogram gradient-boosting comparison.", chart_w, 155),
            image_cell(MODEL / "calibration_brier_ece.png", "Calibration, Brier score, and ECE evidence.", chart_w, 155),
        ]],
        colWidths=[96 * mm, 96 * mm],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        ),
    )
    story.extend(
        [
            charts,
            Spacer(1, 4 * mm),
            evidence_table(
                [
                    ["Evidence", "Measured value", "Release interpretation"],
                    ["Selected portable model", f"Logistic regression; PR-AUC {selected['pr_auc']:.4f}; Brier {selected['brier']:.4f}; ECE {selected['ece']:.4f}", "Demo only; does not satisfy production email gates"],
                    ["User-risk evaluation", f"Top-10% recall {user_risk['top_10_recall']:.2f}; false alerts {user_risk['false_alerts_per_100']:.2f} / 100; median delay {user_risk['median_detection_delay_days']:.1f} day", "Detection target met; false-alert gate not met"],
                    ["ONNX parity", f"Maximum absolute probability difference {metrics['onnx_max_abs_difference']:.2e}", "Passes 1e-5 logistic parity gate"],
                    ["Hybrid weights", "PDF weights 0.35 / 0.20 / 0.20 / 0.15 / 0.10 retained", "No tuned candidate met the promotion improvement rule"],
                    ["Notebook pipeline", "5 parameterized notebooks executed to HTML", "EDA, features, iterations, hybrid evaluation, export/parity"],
                    ["Export bundle", "joblib, ONNX, schemas, thresholds, metrics, coefficients, manifest, model card", "Complete demo artifact; production release correctly blocked"],
                ],
                [48 * mm, 79 * mm, 69 * mm],
            ),
        ]
    )

    # Test details and conclusion
    story.extend(
        [
            PageBreak(),
            p("11. Acceptance results and release posture", "Section"),
            evidence_table(
                [
                    ["Acceptance item", "Evidence", "Status"],
                    ["Runs without company M365 access", "Local signed OIDC + Graph-compatible mock service", "PASS"],
                    ["Continuous incoming mail", "Live counter advance and pause screenshots; browser assertion", "PASS"],
                    ["Attack score update <= 10 seconds", "Strict Playwright polling assertion after sync freshness", "PASS"],
                    ["Tenant isolation", "Signed tenant switch plus RLS / auth tests", "PASS"],
                    ["Privacy", "Header-only schemas, parser tests, and no content fields", "PASS"],
                    ["PostgreSQL integration", "6 integration tests against PostgreSQL", "PASS"],
                    ["API p95 < 300 ms", "6.75 ms local read p95", "PASS"],
                    ["Throughput >= 1,000 metadata events/min", "4,718.3 events/min", "PASS"],
                    ["Compose memory < 8 GB", "465.86 MiB for the five core services", "PASS"],
                    ["Runtime image scan", "Zero fixable high/critical Trivy findings", "PASS"],
                    ["Local CD release", "0.1.0-demo-j checksum/SBOM install and risk smoke", "PASS"],
                    ["Model promotion", "Portable demo model misses production quality gates", "BLOCKED BY DESIGN"],
                    ["Production release", "Release workflow requires an approved immutable model bundle", "SAFELY BLOCKED"],
                ],
                [60 * mm, 104 * mm, 32 * mm],
            ),
            Spacer(1, 8 * mm),
            Table(
                [[p("Conclusion", "Callout"), p(
                    "The requested offline-first platform is runnable and demonstrably testable on the target Mac. "
                    "Its simulator exercises live mail, identity signals, connector failures, analyst feedback, and cross-tenant isolation. "
                    "The runtime and delivery controls are production-minded; the current ML artifact remains explicitly labeled demo until a candidate meets every promotion gate.",
                    "BodyEvidence",
                )]],
                colWidths=[42 * mm, 154 * mm],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), MINT),
                        ("BOX", (0, 0), (-1, -1), 0.7, GREEN),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 9),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                        ("TOPPADDING", (0, 0), (-1, -1), 9),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ]
                ),
            ),
            Spacer(1, 7 * mm),
            p(
                "Reproduction commands: make demo | make scenario NAME=credential-phishing | make test | make integration | make e2e | make benchmark",
                "SmallEvidence",
            ),
            p(
                "Evidence sources: output/playwright, reports/generated, artifacts/models/current, apps/web/e2e/demo.spec.ts.",
                "SmallEvidence",
            ),
        ]
    )

    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    print(OUT)


if __name__ == "__main__":
    build()
