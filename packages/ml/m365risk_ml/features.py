from __future__ import annotations

import hashlib
import re
import tarfile
from collections.abc import Iterator, Mapping
from email.parser import BytesHeaderParser
from email.policy import default
from email.utils import getaddresses
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

FEATURE_NAMES = [
    "header_count",
    "received_hops",
    "recipient_count",
    "missing_message_id",
    "missing_date",
    "from_sender_mismatch",
    "reply_to_mismatch",
    "return_path_mismatch",
    "has_auth_results",
    "has_list_id",
    "has_precedence",
    "has_html_content_type",
    "encoded_from",
    "malformed_message_id",
]
FORBIDDEN_HEADERS = {"x-spam-status", "x-spam-flag", "x-spam-level", "x-spam-checker-version"}
MAX_HEADER_BYTES = 256 * 1024


class HeaderStream(Protocol):
    def readline(self, size: int = -1, /) -> bytes: ...


def read_header_block(stream: HeaderStream, max_bytes: int = MAX_HEADER_BYTES) -> bytes:
    """Read only RFC header lines, with a hard limit for malformed messages."""
    lines: list[bytes] = []
    size = 0
    while size < max_bytes:
        line = stream.readline(min(64 * 1024, max_bytes - size + 1))
        if not line:
            break
        size += len(line)
        if size > max_bytes:
            raise ValueError("Email header block exceeds privacy limit")
        lines.append(line)
        if line in {b"\n", b"\r\n"}:
            break
    return b"".join(lines)


def address_domain(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"@([A-Za-z0-9.-]+)", value)
    return match.group(1).lower().rstrip(".") if match else ""


def header_features(raw: bytes) -> dict[str, float]:
    message = BytesHeaderParser(policy=default).parsebytes(raw)
    safe_names = [name.lower() for name in message.keys() if name.lower() not in FORBIDDEN_HEADERS]
    from_domain = address_domain(message.get("From"))
    sender_domain = address_domain(message.get("Sender")) or from_domain
    reply_domain = address_domain(message.get("Reply-To")) or from_domain
    return_domain = address_domain(message.get("Return-Path")) or from_domain
    recipient_headers = message.get_all("To", []) + message.get_all("Cc", [])
    recipients = [address for _, address in getaddresses(recipient_headers) if address]
    message_id = str(message.get("Message-ID", ""))
    content_type = str(message.get("Content-Type", "")).lower()
    return {
        "header_count": float(len(safe_names)),
        "received_hops": float(len(message.get_all("Received", []))),
        "recipient_count": float(max(1, len(recipients))),
        "missing_message_id": float(not message_id),
        "missing_date": float(not message.get("Date")),
        "from_sender_mismatch": float(bool(from_domain and sender_domain and from_domain != sender_domain)),
        "reply_to_mismatch": float(bool(from_domain and reply_domain and from_domain != reply_domain)),
        "return_path_mismatch": float(bool(from_domain and return_domain and from_domain != return_domain)),
        "has_auth_results": float("authentication-results" in safe_names),
        "has_list_id": float("list-id" in safe_names),
        "has_precedence": float("precedence" in safe_names),
        "has_html_content_type": float("text/html" in content_type or "multipart/alternative" in content_type),
        "encoded_from": float("=?" in str(message.get("From", ""))),
        "malformed_message_id": float(bool(message_id and not re.match(r"^<[^<>\s]+>$", message_id.strip()))),
    }


def _graph_address(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    address = value.get("emailAddress", value)
    if not isinstance(address, Mapping):
        return ""
    return str(address.get("address", ""))


def graph_message_features(
    message: Mapping[str, object], user_id: str, tenant_salt: str
) -> tuple[dict[str, object], dict[str, float]]:
    """Normalize real or simulated Graph metadata without copying message content."""
    raw_headers = message.get("internetMessageHeaders", [])
    headers: list[tuple[str, str]] = []
    if isinstance(raw_headers, list):
        for item in raw_headers:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name", "")).strip().lower()
            if name and name not in FORBIDDEN_HEADERS:
                headers.append((name, str(item.get("value", ""))))

    def first_header(name: str) -> str:
        return next((value for key, value in headers if key == name), "")

    from_address = _graph_address(message.get("from"))
    sender_address = _graph_address(message.get("sender")) or from_address
    recipients_raw = message.get("toRecipients", [])
    cc_raw = message.get("ccRecipients", [])
    recipients = [
        _graph_address(value)
        for group in (recipients_raw, cc_raw)
        if isinstance(group, list)
        for value in group
    ]
    from_domain = address_domain(from_address)
    sender_domain = address_domain(sender_address) or from_domain
    recipient_domains = {address_domain(value) for value in recipients if address_domain(value)}
    reply_domain = address_domain(first_header("reply-to")) or from_domain
    return_domain = address_domain(first_header("return-path")) or from_domain
    message_id = first_header("message-id") or str(message.get("internetMessageId", ""))
    authentication: dict[str, str] = {}
    supplied_auth = message.get("authenticationResults")
    if isinstance(supplied_auth, Mapping):
        # A structured result is supplied by our controlled simulator. Microsoft
        # Graph messages expose Authentication-Results only as a raw header; a
        # sender can prepend a forged one, so it cannot certify SPF/DKIM/DMARC.
        authentication = {str(key).lower(): str(value).lower() for key, value in supplied_auth.items()}

    external_sender = bool(
        message.get("externalSender")
        if "externalSender" in message
        else from_domain and recipient_domains and from_domain not in recipient_domains
    )
    recipient_count = int(str(message.get("recipientCount", 0) or len(recipients) or 1))
    reply_mismatch = bool(
        message.get("replyToDomainMismatch")
        if "replyToDomainMismatch" in message
        else from_domain and reply_domain and from_domain != reply_domain
    )
    sender_mismatch = bool(
        message.get("fromSenderMismatch")
        if "fromSenderMismatch" in message
        else from_domain and sender_domain and from_domain != sender_domain
    )
    received_hops = int(
        str(message.get("receivedHops", 0) or sum(name == "received" for name, _ in headers))
    )
    content_type = first_header("content-type").lower()
    message_hash = hashlib.sha256(
        f"{tenant_salt}:message:{message['id']}".encode()
    ).hexdigest()
    sender_domain_hash = (
        hashlib.sha256(f"{tenant_salt}:domain:{from_domain}".encode()).hexdigest()[:24]
        if from_domain
        else ""
    )
    recipient_domain = sorted(recipient_domains)[0] if recipient_domains else ""
    recipient_domain_hash = (
        hashlib.sha256(f"{tenant_salt}:domain:{recipient_domain}".encode()).hexdigest()[:24]
        if recipient_domain
        else ""
    )
    safe_metadata: dict[str, object] = {
        "id": message_hash,
        "user_id": user_id,
        "received_at": str(message["receivedDateTime"]),
        "external_sender": external_sender,
        "recipient_count": max(1, recipient_count),
        "has_attachments": bool(message.get("hasAttachments", False)),
        "importance": str(message.get("importance", "normal")).lower(),
        "authentication_results": authentication,
        "reply_to_domain_mismatch": reply_mismatch,
        "from_sender_mismatch": sender_mismatch,
        "received_hops": max(0, received_hops),
        "sender_domain_hash": sender_domain_hash,
        "recipient_domain_hash": recipient_domain_hash,
    }
    model_features = {
        "header_count": float(str(len(headers) or message.get("headerCount", 0) or 8)),
        "received_hops": float(received_hops),
        "recipient_count": float(max(1, recipient_count)),
        "missing_message_id": float(not message_id),
        "missing_date": float(not first_header("date") and not message.get("receivedDateTime")),
        "from_sender_mismatch": float(sender_mismatch),
        "reply_to_mismatch": float(reply_mismatch),
        "return_path_mismatch": float(
            bool(from_domain and return_domain and from_domain != return_domain)
        ),
        "has_auth_results": float(bool(first_header("authentication-results") or authentication)),
        "has_list_id": float(bool(first_header("list-id"))),
        "has_precedence": float(bool(first_header("precedence"))),
        "has_html_content_type": float(
            "text/html" in content_type or "multipart/alternative" in content_type
        ),
        "encoded_from": float("=?" in first_header("from")),
        "malformed_message_id": float(
            bool(message_id and not re.match(r"^<[^<>\s]+>$", message_id.strip()))
        ),
    }
    return safe_metadata, model_features


def corpus_rows(archive: Path) -> Iterator[dict[str, object]]:
    label = int("spam" in archive.stem and "ham" not in archive.stem)
    with tarfile.open(archive, "r:bz2") as handle:
        index = 0
        for member in handle:
            if not member.isfile() or member.name.endswith("/cmds"):
                continue
            stream = handle.extractfile(member)
            if stream is None:
                continue
            try:
                features = header_features(read_header_block(stream))
            except Exception:
                continue
            index += 1
            yield {
                **features,
                "label": label,
                "archive": archive.name,
                "sequence": index,
                "message_key": member.name,
            }


def load_spamassassin(root: Path) -> pd.DataFrame:
    import pandas as pd

    rows: list[dict[str, object]] = []
    for archive in sorted(root.glob("20030228_*.tar.bz2")):
        rows.extend(corpus_rows(archive))
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise FileNotFoundError(f"No SpamAssassin messages found in {root}")
    return frame


def chronological_split(frame: pd.DataFrame, test_fraction: float = 0.2) -> tuple[np.ndarray, np.ndarray]:
    train: list[int] = []
    test: list[int] = []
    for _, group in frame.groupby("archive", sort=False):
        boundary = max(1, round(len(group) * (1 - test_fraction)))
        train.extend(group.index[:boundary])
        test.extend(group.index[boundary:])
    return np.asarray(train), np.asarray(test)
