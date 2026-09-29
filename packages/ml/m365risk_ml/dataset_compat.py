from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

V2_EMAIL_REQUIRED = {
    "label",
    "received_at",
    "recipient_count",
    "received_hops",
    "external_sender",
    "reply_to_domain_mismatch",
    "from_sender_mismatch",
    "spf_result",
    "dkim_result",
    "dmarc_result",
}
V2_IDENTITY_REQUIRED = {
    "user_id",
    "created_at",
    "successful",
    "country",
    "network_hash",
    "device_hash",
    "app_hash",
}
FORBIDDEN_CONTENT_FIELDS = {
    "subject",
    "body",
    "body_preview",
    "unique_body",
    "attachment_bytes",
    "ip_address",
}


@dataclass(frozen=True)
class CompatibilityReport:
    compatible: bool
    production_eligible: bool
    source_category: str
    present: list[str]
    missing: list[str]
    forbidden: list[str]
    warnings: list[str]


def dataset_preflight(
    columns: Iterable[str],
    *,
    dataset_kind: str,
    source_category: str,
    labelled: bool,
) -> CompatibilityReport:
    normalized = {str(column).strip().lower() for column in columns}
    required = V2_EMAIL_REQUIRED if dataset_kind == "email" else V2_IDENTITY_REQUIRED
    forbidden = sorted(normalized & FORBIDDEN_CONTENT_FIELDS)
    missing = sorted(required - normalized)
    present = sorted(required & normalized)
    warnings: list[str] = []
    if source_category not in {"imported", "generated", "real_labelled"}:
        warnings.append("Source category must be imported, generated, or real_labelled")
    if not labelled:
        warnings.append("Dataset has no reviewed outcome labels")
    if source_category != "real_labelled":
        warnings.append("Dataset cannot approve a production model without real Microsoft 365 labels")
    if missing:
        warnings.append("Missing fields must remain unknown; they may not be imputed as safe")
    compatible = not forbidden and not missing
    production_eligible = compatible and labelled and source_category == "real_labelled"
    return CompatibilityReport(
        compatible=compatible,
        production_eligible=production_eligible,
        source_category=source_category,
        present=present,
        missing=missing,
        forbidden=forbidden,
        warnings=warnings,
    )


def adapt_v1_email_row(row: Mapping[str, object]) -> dict[str, object]:
    """Map legacy metadata while preserving absent modern authentication as unknown."""
    return {
        "label": row.get("label"),
        "received_at": row.get("received_at"),
        "recipient_count": row.get("recipient_count"),
        "received_hops": row.get("received_hops"),
        "external_sender": row.get("external_sender"),
        "reply_to_domain_mismatch": row.get("reply_to_mismatch"),
        "from_sender_mismatch": row.get("from_sender_mismatch"),
        "spf_result": row.get("spf_result"),
        "dkim_result": row.get("dkim_result"),
        "dmarc_result": row.get("dmarc_result"),
        "auth_available": all(
            row.get(name) is not None for name in ("spf_result", "dkim_result", "dmarc_result")
        ),
    }
