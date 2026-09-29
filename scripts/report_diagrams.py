"""Vector architecture and UML-style diagrams for the evidence report."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from pathlib import Path

from reportlab.graphics import renderSVG
from reportlab.graphics.shapes import Circle, Drawing, Ellipse, Line, Polygon, Rect, String
from reportlab.lib import colors

INK = colors.HexColor("#11261f")
MUTED = colors.HexColor("#52645d")
GREEN = colors.HexColor("#087f5b")
GREEN_DARK = colors.HexColor("#07543f")
MINT = colors.HexColor("#dff6ec")
PALE = colors.HexColor("#f4f8f6")
AMBER = colors.HexColor("#b36b00")
AMBER_PALE = colors.HexColor("#fff4d6")
RED = colors.HexColor("#b42318")
RED_PALE = colors.HexColor("#fee4e2")
BLUE = colors.HexColor("#175cd3")
BLUE_PALE = colors.HexColor("#eaf2ff")
PURPLE = colors.HexColor("#6941c6")
PURPLE_PALE = colors.HexColor("#f1ebff")
LINE = colors.HexColor("#b9ccc4")
WHITE = colors.white

WIDTH = 752
HEIGHT = 410


def _text(
    drawing: Drawing,
    x: float,
    y: float,
    lines: str | Iterable[str],
    *,
    size: float = 9,
    color=INK,
    bold: bool = False,
    anchor: str = "middle",
    leading: float | None = None,
) -> None:
    values = [lines] if isinstance(lines, str) else list(lines)
    step = leading or size * 1.28
    for index, value in enumerate(values):
        drawing.add(
            String(
                x,
                y - index * step,
                str(value),
                fontName="Helvetica-Bold" if bold else "Helvetica",
                fontSize=size,
                fillColor=color,
                textAnchor=anchor,
            )
        )


def _box(
    drawing: Drawing,
    x: float,
    y: float,
    width: float,
    height: float,
    title: str,
    lines: Iterable[str] = (),
    *,
    fill=PALE,
    stroke=LINE,
    title_color=INK,
    radius: float = 8,
) -> None:
    drawing.add(
        Rect(
            x,
            y,
            width,
            height,
            rx=radius,
            ry=radius,
            fillColor=fill,
            strokeColor=stroke,
            strokeWidth=1.2,
        )
    )
    _text(
        drawing,
        x + width / 2,
        y + height - 18,
        title,
        size=10,
        color=title_color,
        bold=True,
    )
    body = list(lines)
    if body:
        _text(
            drawing,
            x + width / 2,
            y + height - 36,
            body,
            size=7.4,
            color=MUTED,
            leading=10.5,
        )


def _boundary(
    drawing: Drawing,
    x: float,
    y: float,
    width: float,
    height: float,
    label: str,
    *,
    color=GREEN,
) -> None:
    drawing.add(
        Rect(
            x,
            y,
            width,
            height,
            rx=10,
            ry=10,
            fillColor=colors.Color(1, 1, 1, alpha=0),
            strokeColor=color,
            strokeWidth=1.4,
            strokeDashArray=[6, 4],
        )
    )
    drawing.add(
        Rect(
            x + 12,
            y + height - 13,
            max(92, len(label) * 5.7),
            22,
            rx=5,
            ry=5,
            fillColor=WHITE,
            strokeColor=color,
            strokeWidth=1,
        )
    )
    _text(
        drawing,
        x + 22,
        y + height - 6,
        label,
        size=8,
        color=color,
        bold=True,
        anchor="start",
    )


def _arrow(
    drawing: Drawing,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    label: str = "",
    *,
    color=GREEN_DARK,
    dashed: bool = False,
    label_offset: float = 8,
) -> None:
    drawing.add(
        Line(
            x1,
            y1,
            x2,
            y2,
            strokeColor=color,
            strokeWidth=1.35,
            strokeDashArray=[5, 4] if dashed else None,
        )
    )
    angle = math.atan2(y2 - y1, x2 - x1)
    head = 8
    spread = 0.48
    p1 = (x2, y2)
    p2 = (x2 - head * math.cos(angle - spread), y2 - head * math.sin(angle - spread))
    p3 = (x2 - head * math.cos(angle + spread), y2 - head * math.sin(angle + spread))
    drawing.add(
        Polygon(
            [p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]],
            fillColor=color,
            strokeColor=color,
        )
    )
    if label:
        midpoint_x = (x1 + x2) / 2
        midpoint_y = (y1 + y2) / 2 + label_offset
        drawing.add(
            Rect(
                midpoint_x - max(26, len(label) * 2.25),
                midpoint_y - 6,
                max(52, len(label) * 4.5),
                13,
                rx=3,
                ry=3,
                fillColor=WHITE,
                strokeColor=None,
            )
        )
        _text(drawing, midpoint_x, midpoint_y - 2, label, size=6.8, color=color)


def _actor(drawing: Drawing, x: float, y: float, label: str) -> None:
    drawing.add(Circle(x, y + 40, 10, fillColor=WHITE, strokeColor=GREEN_DARK, strokeWidth=1.5))
    drawing.add(Line(x, y + 30, x, y, strokeColor=GREEN_DARK, strokeWidth=1.5))
    drawing.add(Line(x - 15, y + 20, x + 15, y + 20, strokeColor=GREEN_DARK, strokeWidth=1.5))
    drawing.add(Line(x, y, x - 13, y - 20, strokeColor=GREEN_DARK, strokeWidth=1.5))
    drawing.add(Line(x, y, x + 13, y - 20, strokeColor=GREEN_DARK, strokeWidth=1.5))
    _text(drawing, x, y - 35, label, size=8, color=INK, bold=True)


def _use_case(drawing: Drawing, x: float, y: float, width: float, label: str, fill=MINT) -> None:
    drawing.add(
        Ellipse(
            x,
            y,
            width / 2,
            25,
            fillColor=fill,
            strokeColor=GREEN,
            strokeWidth=1.1,
        )
    )
    _text(drawing, x, y + 2, label.split("\n"), size=7.4, color=INK, bold=True, leading=9)


def _participant(drawing: Drawing, x: float, title: str, subtitle: str = "") -> None:
    _box(
        drawing,
        x - 58,
        354,
        116,
        42,
        title,
        [subtitle] if subtitle else (),
        fill=BLUE_PALE,
        stroke=BLUE,
        title_color=BLUE,
        radius=5,
    )
    drawing.add(
        Line(
            x,
            354,
            x,
            38,
            strokeColor=LINE,
            strokeWidth=1,
            strokeDashArray=[4, 4],
        )
    )


def _message(
    drawing: Drawing,
    y: float,
    x1: float,
    x2: float,
    label: str,
    *,
    response: bool = False,
    color=GREEN_DARK,
) -> None:
    _arrow(drawing, x1, y, x2, y, label, color=color, dashed=response, label_offset=9)


def system_context_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    _boundary(d, 242, 85, 280, 250, "M365 User Risk Platform")
    _box(
        d,
        275,
        145,
        215,
        135,
        "Risk analytics platform",
        [
            "Next.js analyst dashboard",
            "FastAPI tenant API",
            "PostgreSQL queue and RLS data",
            "Worker + model inference",
        ],
        fill=MINT,
        stroke=GREEN,
        title_color=GREEN_DARK,
    )
    _actor(d, 70, 265, "Security analyst")
    _actor(d, 70, 105, "Tenant administrator")
    _box(d, 585, 260, 145, 78, "Microsoft 365", ["Graph mail metadata", "Entra identity signals"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _box(d, 585, 125, 145, 78, "Offline simulator", ["Mock Graph + OIDC", "Deterministic attacks"], fill=PURPLE_PALE, stroke=PURPLE, title_color=PURPLE)
    _box(d, 295, 18, 175, 50, "GitHub Actions", ["CI, model and local release"], fill=AMBER_PALE, stroke=AMBER, title_color=AMBER)
    _arrow(d, 92, 270, 275, 245, "triage, explain, feedback")
    _arrow(d, 92, 110, 275, 175, "consent, sync, scenarios")
    _arrow(d, 490, 245, 585, 295, "real connector")
    _arrow(d, 585, 160, 490, 190, "mock connector")
    _arrow(d, 382, 68, 382, 145, "versioned release")
    return d


def use_case_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    _boundary(d, 145, 25, 585, 360, "System use cases")
    _actor(d, 55, 275, "Security analyst")
    _actor(d, 55, 100, "Tenant administrator")
    _use_case(d, 275, 325, 190, "Authenticate with\nsigned tenant role")
    _use_case(d, 490, 325, 180, "Review dashboard\nand freshness")
    _use_case(d, 275, 245, 190, "Search users and\ninspect risk history")
    _use_case(d, 490, 245, 180, "Explain score and\nrecord feedback")
    _use_case(d, 275, 155, 190, "Onboard connector\nand grant consent")
    _use_case(d, 490, 155, 180, "Start sync and\nmonitor jobs")
    _use_case(d, 275, 70, 190, "Run attack and\nfailure scenarios", fill=AMBER_PALE)
    _use_case(d, 490, 70, 180, "Pause, recover and\nreset simulator", fill=AMBER_PALE)
    for target_y in (325, 245):
        _arrow(d, 85, 305 if target_y == 325 else 280, 180, target_y, color=MUTED)
    _arrow(d, 85, 285, 400, 325, color=MUTED)
    _arrow(d, 85, 255, 400, 245, color=MUTED)
    for target_x, target_y in ((180, 155), (400, 155), (180, 70), (400, 70)):
        _arrow(d, 85, 120, target_x, target_y, color=MUTED)
    _text(d, 615, 38, ["Admin-only simulator controls", "exist only in mock mode"], size=7, color=AMBER, bold=True)
    return d


def container_architecture_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    _boundary(d, 16, 38, 130, 325, "Client")
    _box(d, 32, 235, 98, 88, "Browser", ["Next.js UI", "TanStack Query", "signed JWT"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _boundary(d, 165, 38, 405, 325, "Application network")
    _box(d, 185, 260, 150, 75, "Web container", ["Next.js 16", "generated API types"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _box(d, 385, 260, 150, 75, "API container", ["FastAPI", "JWT + tenant context", "OpenAPI + metrics"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _box(d, 185, 115, 150, 85, "Worker container", ["SKIP LOCKED queue", "delta sync + retries", "risk recomputation"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _box(d, 385, 105, 150, 95, "PostgreSQL 17", ["forced row-level security", "jobs, features, scores", "feedback + audit"], fill=AMBER_PALE, stroke=AMBER, title_color=AMBER)
    _boundary(d, 590, 38, 155, 325, "Connector targets", color=PURPLE)
    _box(d, 610, 260, 115, 75, "Real Graph", ["tenant tokens", "delta + identity"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _box(d, 610, 125, 115, 95, "Mock Graph/OIDC", ["JWKS + signed tokens", "mail every 2 seconds", "scenario controls"], fill=PURPLE_PALE, stroke=PURPLE, title_color=PURPLE)
    _arrow(d, 130, 278, 185, 298, "HTTPS")
    _arrow(d, 335, 298, 385, 298, "bearer JWT")
    _arrow(d, 460, 260, 460, 200, "tenant SQL")
    _arrow(d, 385, 152, 335, 152, "claim jobs", dashed=True)
    _arrow(d, 335, 170, 385, 170, "features + scores")
    _arrow(d, 535, 300, 610, 298, "real mode")
    _arrow(d, 535, 178, 610, 175, "mock mode")
    return d


def deployment_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    _boundary(d, 22, 35, 495, 345, "Apple Silicon Mac - local production-like deployment")
    _box(d, 42, 285, 115, 62, "Host browser", ["localhost:3000", "localhost:8000/docs"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _boundary(d, 180, 65, 315, 282, "Docker Compose risk-net")
    _box(d, 198, 260, 85, 55, "web", ["ARM64 image"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _box(d, 305, 260, 85, 55, "api", ["ARM64 image"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _box(d, 412, 260, 65, 55, "worker", ["shared", "Python"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _box(d, 220, 145, 105, 62, "PostgreSQL", ["named volume", "backup dump"], fill=AMBER_PALE, stroke=AMBER, title_color=AMBER)
    _box(d, 355, 145, 105, 62, "Mock Graph", ["OIDC + simulator"], fill=PURPLE_PALE, stroke=PURPLE, title_color=PURPLE)
    _box(d, 245, 78, 190, 42, "Optional observability profile", ["OTel Collector + Prometheus + Grafana"], fill=PALE, stroke=LINE)
    _boundary(d, 548, 35, 195, 345, "Delivery plane", color=AMBER)
    _box(d, 570, 285, 150, 62, "GitHub Actions", ["CI + model + release"], fill=AMBER_PALE, stroke=AMBER, title_color=AMBER)
    _box(d, 570, 185, 150, 62, "Immutable bundle", ["OCI images + SBOMs", "checksums + migrations"], fill=PALE, stroke=AMBER, title_color=AMBER)
    _box(d, 570, 82, 150, 62, "Local installer", ["backup -> migrate -> health", "retain previous release"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _arrow(d, 157, 315, 198, 290, "localhost")
    _arrow(d, 283, 280, 305, 280)
    _arrow(d, 390, 280, 412, 280)
    _arrow(d, 347, 260, 277, 207, "RLS SQL")
    _arrow(d, 438, 260, 408, 207, "mock Graph")
    _arrow(d, 645, 285, 645, 247, "build")
    _arrow(d, 645, 185, 645, 144, "install")
    _arrow(d, 570, 113, 495, 113, "load + deploy")
    return d


def auth_sequence_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    xs = [75, 220, 365, 510, 675]
    for x, title, subtitle in zip(
        xs,
        ["Analyst", "Next.js", "FastAPI", "Mock OIDC/JWKS", "PostgreSQL"],
        ["browser", "dashboard", "tenant API", "signed identity", "forced RLS"],
        strict=True,
    ):
        _participant(d, x, title, subtitle)
    messages = [
        (326, 75, 220, "1. Select tenant and role", False, GREEN_DARK),
        (292, 220, 510, "2. Request signed authorization", False, PURPLE),
        (258, 510, 220, "3. JWT with tid + roles", True, PURPLE),
        (224, 220, 365, "4. API request + bearer token", False, GREEN_DARK),
        (190, 365, 510, "5. Resolve JWKS; verify iss/aud/signature", False, BLUE),
        (156, 365, 675, "6. SET LOCAL app.tenant_id = verified tid", False, AMBER),
        (122, 675, 365, "7. RLS-scoped rows only", True, AMBER),
        (88, 365, 220, "8. Tenant-safe response", True, GREEN_DARK),
        (54, 220, 75, "9. Render authorized dashboard", True, GREEN_DARK),
    ]
    for row in messages:
        _message(d, *row[:4], response=row[4], color=row[5])
    return d


def sync_scoring_sequence_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    xs = [68, 205, 342, 480, 615, 710]
    for x, title, subtitle in zip(
        xs,
        ["Scheduler", "PostgreSQL", "Worker", "Graph adapter", "Inference", "Dashboard"],
        ["idempotency", "queue + RLS", "SKIP LOCKED", "real or mock", "joblib/ONNX", "poll <= 10 s"],
        strict=True,
    ):
        _participant(d, x, title, subtitle)
    messages = [
        (326, 68, 205, "1. Enqueue tenant sync", False, GREEN_DARK),
        (294, 342, 205, "2. Claim job FOR UPDATE SKIP LOCKED", False, AMBER),
        (262, 205, 342, "3. Job + checkpoint + tenant context", True, AMBER),
        (230, 342, 480, "4. Delta request with exact select", False, BLUE),
        (198, 480, 342, "5. Page + next/delta link or Retry-After", True, BLUE),
        (166, 342, 205, "6. Upsert metadata and daily features", False, AMBER),
        (134, 342, 615, "7. Score email + behavior + identity", False, GREEN),
        (102, 615, 342, "8. Probability + explanation", True, GREEN),
        (70, 342, 205, "9. Persist score, factors, model version", False, AMBER),
        (42, 710, 205, "10. Read tenant-scoped update", False, PURPLE),
    ]
    for row in messages:
        _message(d, *row[:4], response=row[4], color=row[5])
    return d


def scenario_sequence_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    xs = [70, 210, 350, 490, 625, 710]
    for x, title, subtitle in zip(
        xs,
        ["Admin", "Dashboard", "FastAPI", "Mock Graph", "Worker", "Risk view"],
        ["localhost", "scenario control", "idempotency", "event generator", "delta consumer", "live feedback"],
        strict=True,
    ):
        _participant(d, x, title, subtitle)
    messages = [
        (324, 70, 210, "1. Choose credential phishing", False, AMBER),
        (290, 210, 350, "2. POST scenario + Idempotency-Key", False, AMBER),
        (256, 350, 490, "3. Start deterministic scenario", False, PURPLE),
        (222, 490, 490, "4. Emit header-only event every 2 s", False, PURPLE),
        (188, 625, 490, "5. Request delta page", False, BLUE),
        (154, 490, 625, "6. SPF/DKIM/DMARC fail + route signals", True, RED),
        (120, 625, 350, "7. Persist score and factors", False, GREEN),
        (86, 710, 350, "8. Poll mail events and risk summaries", False, GREEN_DARK),
        (52, 350, 710, "9. High-risk telemetry and score update", True, RED),
    ]
    for row in messages:
        _message(d, *row[:4], response=row[4], color=row[5])
    return d


def privacy_data_flow_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    _box(d, 25, 265, 130, 85, "Input sources", ["SpamAssassin", "Enron", "Graph message delta"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _box(d, 220, 265, 150, 85, "Privacy parser", ["headers only", "allowlisted fields", "UTC normalization"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _box(d, 435, 265, 135, 85, "Feature layer", ["EmailMetadataV1", "daily aggregates", "behavior baselines"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _box(d, 620, 265, 115, 85, "PostgreSQL", ["tenant_id", "forced RLS", "retention jobs"], fill=AMBER_PALE, stroke=AMBER, title_color=AMBER)
    _box(d, 435, 95, 135, 82, "Risk inference", ["versioned model", "hybrid weights", "explanations"], fill=PURPLE_PALE, stroke=PURPLE, title_color=PURPLE)
    _box(d, 620, 95, 115, 82, "Analyst API/UI", ["safe telemetry", "risk + factors", "feedback"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _box(d, 220, 80, 150, 98, "Discarded at boundary", ["subject", "body / preview", "unique body", "attachment bytes"], fill=RED_PALE, stroke=RED, title_color=RED)
    _arrow(d, 155, 308, 220, 308, "raw message input", color=BLUE)
    _arrow(d, 370, 308, 435, 308, "safe metadata", color=GREEN)
    _arrow(d, 570, 308, 620, 308, "partitioned/tenant rows", color=AMBER)
    _arrow(d, 688, 265, 535, 177, "features", color=PURPLE)
    _arrow(d, 570, 136, 620, 136, "risk + explanation", color=GREEN_DARK)
    _arrow(d, 295, 265, 295, 178, "never persisted", color=RED)
    _text(d, 95, 215, ["Trust boundary:", "only validated JWT tid", "selects tenant context"], size=8, color=GREEN_DARK, bold=True)
    _text(d, 675, 42, ["No content fields leave the parser", "or appear in logs, API, Parquet, or UI"], size=8, color=RED, bold=True)
    return d


def data_model_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    _box(d, 320, 340, 120, 50, "Tenant", ["id, name"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    entities = [
        (25, 245, "Connection", ["connector mode", "encrypted credential"]),
        (165, 245, "User", ["external id", "MFA / privilege"]),
        (305, 245, "SyncJob", ["status, attempts", "delta checkpoint"]),
        (445, 245, "EmailFeature", ["received_at", "header signals"]),
        (590, 245, "DailyFeature", ["behavior aggregates", "feature version"]),
        (20, 105, "RiskScore", ["score, level", "model version"]),
        (165, 105, "RiskFactor", ["factor, contribution", "explanation"]),
        (310, 105, "Feedback", ["label, note", "analyst role"]),
        (455, 105, "ModelVersion", ["approval status", "metrics + hashes"]),
        (600, 105, "AuditEvent", ["request id", "redacted tenant"]),
    ]
    for x, y, title, body in entities:
        fill = BLUE_PALE if title in {"Connection", "User"} else PALE
        stroke = BLUE if title in {"Connection", "User"} else LINE
        _box(d, x, y, 125, 72, title, body, fill=fill, stroke=stroke, title_color=INK)
    for x in (87, 227, 367, 507, 652):
        _arrow(d, 380, 340, x, 317, "1 : many", color=MUTED)
    _arrow(d, 227, 245, 82, 177, "user scores", color=GREEN_DARK)
    _arrow(d, 145, 141, 165, 141, "factors", color=GREEN_DARK)
    _arrow(d, 290, 141, 310, 141, "analyst labels", color=PURPLE)
    _arrow(d, 507, 245, 662, 177, "audited writes", color=AMBER)
    _text(d, 380, 48, ["Every business table carries tenant_id.", "Composite tenant keys and tenant-first indexes prevent cross-tenant joins."], size=8.5, color=GREEN_DARK, bold=True)
    return d


def model_lifecycle_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    boxes = [
        (20, 285, 105, "Datasets", ["checksums", "header-only"]),
        (145, 285, 105, "Feature build", ["partitioned Parquet", "schema V1"]),
        (270, 285, 105, "Time/group split", ["train", "validation", "test"]),
        (395, 285, 105, "Candidates", ["rules", "logistic", "HistGB"]),
        (520, 285, 105, "Calibrate", ["thresholds", "Brier + ECE"]),
        (645, 285, 95, "Evaluate", ["PR/ROC", "top-k delay"]),
    ]
    for x, y, width, title, body in boxes:
        _box(d, x, y, width, 72, title, body, fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    for left, right in zip(boxes, boxes[1:], strict=False):
        _arrow(d, left[0] + left[2], 321, right[0], 321)
    _box(d, 290, 150, 180, 82, "Promotion gate", ["email quality + calibration", "user top-k + false alerts", "joblib / ONNX parity"], fill=AMBER_PALE, stroke=AMBER, title_color=AMBER)
    _arrow(d, 692, 285, 470, 205, "recomputed from artifacts", color=AMBER)
    _box(d, 70, 45, 205, 70, "Approved immutable bundle", ["manifest + hashes", "joblib + ONNX + schemas", "eligible for production release"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _box(d, 485, 45, 205, 70, "Demo bundle", ["explicit approved=false", "offline evaluation only", "production release blocked"], fill=RED_PALE, stroke=RED, title_color=RED)
    _arrow(d, 290, 175, 275, 80, "all gates pass", color=GREEN)
    _arrow(d, 470, 175, 485, 80, "any gate fails", color=RED)
    return d


def hybrid_score_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    factors = [
        (25, 300, "Email threat", "0.35", RED_PALE, RED),
        (25, 230, "Behavior anomaly", "0.20", AMBER_PALE, AMBER),
        (25, 160, "Identity risk", "0.20", PURPLE_PALE, PURPLE),
        (25, 90, "MFA posture", "0.15", BLUE_PALE, BLUE),
        (25, 20, "Privilege exposure", "0.10", PALE, GREEN_DARK),
    ]
    for x, y, title, weight, fill, stroke in factors:
        _box(d, x, y, 180, 52, title, [f"default weight {weight}"], fill=fill, stroke=stroke, title_color=stroke)
        _arrow(d, 205, y + 26, 340, 205, f"x {weight}", color=stroke)
    _box(d, 340, 145, 165, 120, "Hybrid risk score", ["non-negative weighted sum", "0-100 normalized score", "versioned thresholds"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _box(d, 575, 275, 155, 65, "Critical", ["immediate review"], fill=RED_PALE, stroke=RED, title_color=RED)
    _box(d, 575, 190, 155, 65, "High / medium", ["analyst triage queue"], fill=AMBER_PALE, stroke=AMBER, title_color=AMBER)
    _box(d, 575, 105, 155, 65, "Low", ["continuous monitoring"], fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
    _box(d, 575, 20, 155, 65, "Contributing factors", ["human-readable evidence", "recommended actions"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _arrow(d, 505, 220, 575, 307, "threshold")
    _arrow(d, 505, 210, 575, 222, "threshold")
    _arrow(d, 505, 195, 575, 137, "threshold")
    _arrow(d, 505, 175, 575, 52, "explain")
    return d


def cicd_diagram() -> Drawing:
    d = Drawing(WIDTH, HEIGHT)
    _box(d, 20, 315, 100, 55, "Developer", ["pull request / tag"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _box(d, 150, 315, 125, 55, "GitHub Actions", ["pinned runners"], fill=PALE, stroke=LINE)
    _arrow(d, 120, 342, 150, 342, "push")
    ci = [
        (25, 205, "Quality", ["Ruff, mypy", "ESLint, TypeScript"]),
        (165, 205, "Tests", ["pytest + RLS", "Vitest + Playwright"]),
        (305, 205, "Contracts", ["migrations", "OpenAPI drift"]),
        (445, 205, "Security", ["audits + Gitleaks", "Trivy + SBOM"]),
        (585, 205, "Architecture", ["AMD64 build", "ARM64 validation"]),
    ]
    for x, y, title, body in ci:
        _box(d, x, y, 125, 70, title, body, fill=MINT, stroke=GREEN, title_color=GREEN_DARK)
        _arrow(d, 212, 315, x + 62, 275, color=MUTED)
    _box(d, 65, 70, 185, 70, "models.yml - manual", ["download + checksums", "five notebooks + gates", "immutable model artifact"], fill=PURPLE_PALE, stroke=PURPLE, title_color=PURPLE)
    _box(d, 290, 70, 185, 70, "release-local.yml - tag", ["approved model required", "multi-arch OCI + checksums", "SBOM + installer bundle"], fill=AMBER_PALE, stroke=AMBER, title_color=AMBER)
    _box(d, 515, 70, 185, 70, "Local CD", ["backup + migrate + start", "health + E2E smoke", "retain prior rollback"], fill=BLUE_PALE, stroke=BLUE, title_color=BLUE)
    _arrow(d, 150, 205, 157, 140, "model workflow", color=PURPLE)
    _arrow(d, 507, 205, 382, 140, "tag release", color=AMBER)
    _arrow(d, 475, 105, 515, 105, "install bundle", color=BLUE)
    _text(d, 380, 25, ["Production release stops unless an approved, hash-consistent model bundle is present."], size=8.5, color=RED, bold=True)
    return d


DIAGRAMS = [
    (
        "A1. System context diagram",
        "Actors, external services, and the platform boundary.",
        system_context_diagram,
        "Shows who uses the platform, which Microsoft 365 signals enter it, how offline simulation replaces company access, and where CI/CD supplies versioned releases.",
    ),
    (
        "A2. UML use case diagram",
        "Security analyst and tenant-administrator capabilities.",
        use_case_diagram,
        "Separates day-to-day analyst workflows from tenant administration and mock-only scenario controls.",
    ),
    (
        "A3. Container and component architecture",
        "Runtime services and their primary protocols.",
        container_architecture_diagram,
        "The same connector interface selects real or mock Microsoft Graph. PostgreSQL is both the system of record and the durable worker queue.",
    ),
    (
        "A4. Deployment diagram",
        "Local production-like topology and the delivery plane.",
        deployment_diagram,
        "The target Mac runs five core Compose services on a private network. Release bundles carry images, checksums, SBOMs, migrations, backup tooling, and rollback metadata.",
    ),
    (
        "A5. Authentication and tenant-isolation sequence",
        "How a signed tenant identity becomes a forced-RLS database context.",
        auth_sequence_diagram,
        "The tenant identifier is derived only from verified JWT claims. Each transaction sets the tenant context before PostgreSQL evaluates forced row-level-security policies.",
    ),
    (
        "A6. Graph delta synchronization and scoring sequence",
        "Durable jobs, resumable connector state, inference, and dashboard freshness.",
        sync_scoring_sequence_diagram,
        "Idempotent sync jobs can resume from checkpoints. Paging, throttling, scoring, explanations, and persistence remain tenant-scoped.",
    ),
    (
        "A7. Offline scenario and live-mail sequence",
        "Credential-phishing injection from the UI to visible risk evidence.",
        scenario_sequence_diagram,
        "The simulator emits metadata-only mail continuously. The worker consumes the same Graph-compatible delta contract used by the real connector.",
    ),
    (
        "A8. Privacy-aware data-flow diagram",
        "Data minimization and trust boundaries.",
        privacy_data_flow_diagram,
        "Subject, message content, previews, unique body values, and attachment bytes are discarded at the parser boundary and never reach persistence, APIs, logs, or the dashboard.",
    ),
    (
        "A9. Logical data model / ER diagram",
        "Tenant ownership and the main business entities.",
        data_model_diagram,
        "Every business entity carries tenant_id. Composite tenant relationships, tenant-first indexes, and forced RLS provide defense in depth.",
    ),
    (
        "A10. ML activity and promotion lifecycle",
        "From immutable datasets to approved or demo artifacts.",
        model_lifecycle_diagram,
        "Validation selects candidates and thresholds before final holdout evaluation. The promotion checker recomputes gates and artifact hashes rather than trusting a label.",
    ),
    (
        "A11. Hybrid risk-score composition",
        "Default PDF weights, thresholds, and explainability outputs.",
        hybrid_score_diagram,
        "Tuned non-negative weights are promoted only when top-10 recall improves by at least five points without increasing false alerts; otherwise the documented defaults remain.",
    ),
    (
        "A12. CI/CD and release activity diagram",
        "Quality, security, model, release, install, and rollback gates.",
        cicd_diagram,
        "PRs gate quality, data, browser, security, and architectures. Tags require an approved model.",
    ),
]


def export_diagrams(output_dir: Path) -> list[Path]:
    """Export every defense diagram as a standalone editable SVG asset."""
    output_dir.mkdir(parents=True, exist_ok=True)
    exported: list[Path] = []
    for title, _subtitle, factory, _note in DIAGRAMS:
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        destination = output_dir / f"{slug}.svg"
        renderSVG.drawToFile(factory(), str(destination))
        exported.append(destination)
    return exported


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    files = export_diagrams(root / "output" / "diagrams")
    print(f"Exported {len(files)} diagrams to {files[0].parent}")
