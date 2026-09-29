from __future__ import annotations

from packages.ml.m365risk_ml.dataset_compat import (
    V2_EMAIL_REQUIRED,
    adapt_v1_email_row,
    dataset_preflight,
)


def test_preflight_blocks_forbidden_content_before_upload() -> None:
    report = dataset_preflight(
        [*V2_EMAIL_REQUIRED, "body", "ip_address"],
        dataset_kind="email",
        source_category="real_labelled",
        labelled=True,
    )
    assert not report.compatible
    assert report.forbidden == ["body", "ip_address"]


def test_imported_dataset_can_be_compatible_but_not_production_eligible() -> None:
    report = dataset_preflight(
        V2_EMAIL_REQUIRED,
        dataset_kind="email",
        source_category="imported",
        labelled=True,
    )
    assert report.compatible
    assert not report.production_eligible


def test_v1_adapter_uses_missing_mask_instead_of_fake_authentication() -> None:
    adapted = adapt_v1_email_row({"label": 1, "recipient_count": 2})
    assert adapted["spf_result"] is None
    assert adapted["auth_available"] is False
