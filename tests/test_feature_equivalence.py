from __future__ import annotations

from packages.ml.m365risk_ml.features import graph_message_features, header_features


def test_recipient_count_matches_between_training_and_graph_paths() -> None:
    raw = (
        b"From: Sender <sender@external.example>\r\n"
        b"To: One <one@tenant.example>, Two <two@tenant.example>\r\n"
        b"Cc: three@tenant.example\r\n"
        b"Message-ID: <one@external.example>\r\n"
        b"Date: Tue, 1 Jan 2026 10:00:00 +0000\r\n\r\n"
    )
    offline = header_features(raw)
    _, online = graph_message_features(
        {
            "id": "message-1",
            "receivedDateTime": "2026-01-01T10:00:00Z",
            "from": {"emailAddress": {"address": "sender@external.example"}},
            "sender": {"emailAddress": {"address": "sender@external.example"}},
            "toRecipients": [
                {"emailAddress": {"address": "one@tenant.example"}},
                {"emailAddress": {"address": "two@tenant.example"}},
            ],
            "ccRecipients": [{"emailAddress": {"address": "three@tenant.example"}}],
            "internetMessageHeaders": [
                {"name": "Message-ID", "value": "<one@external.example>"},
                {"name": "Date", "value": "Tue, 1 Jan 2026 10:00:00 +0000"},
            ],
        },
        "user-1",
        "tenant-key",
    )
    assert offline["recipient_count"] == 3
    assert online["recipient_count"] == offline["recipient_count"]
