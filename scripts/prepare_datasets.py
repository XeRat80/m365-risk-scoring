#!/usr/bin/env python3
"""Create privacy-safe, partitioned Parquet metadata from public mail archives."""

from __future__ import annotations

import argparse
import hashlib
import os
import tarfile
from datetime import UTC, datetime
from email.parser import BytesHeaderParser
from email.policy import default
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as ds

from packages.ml.m365risk_ml.features import (
    FEATURE_NAMES,
    corpus_rows,
    header_features,
    read_header_block,
)

TENANT = "offline-public"
OUTPUT_SCHEMA = pa.schema(
    [*(pa.field(name, pa.float64()) for name in FEATURE_NAMES)]
    + [
        pa.field("label", pa.int8()),
        pa.field("sender_hash", pa.string()),
        pa.field("recipient_hash", pa.string()),
        pa.field("received_at", pa.timestamp("us", tz="UTC")),
        pa.field("dataset", pa.string()),
        pa.field("date", pa.string()),
        pa.field("tenant_id", pa.string()),
    ]
)


def pseudonym(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value.strip().lower()}".encode()).hexdigest()[:24]


def write_batch(rows: list[dict[str, object]], destination: Path, batch: int) -> None:
    if not rows:
        return
    destination.mkdir(parents=True, exist_ok=True)
    ds.write_dataset(
        pa.Table.from_pylist(rows, schema=OUTPUT_SCHEMA),
        destination,
        format="parquet",
        partitioning=["dataset", "date", "tenant_id"],
        partitioning_flavor="hive",
        basename_template=f"part-{batch:05d}-{{i}}.parquet",
        existing_data_behavior="overwrite_or_ignore",
    )


def spamassassin(root: Path, destination: Path) -> int:
    rows: list[dict[str, object]] = []
    batch = 0
    count = 0
    for archive in sorted(root.glob("20030228_*.tar.bz2")):
        for item in corpus_rows(archive):
            rows.append(
                {
                    **{key: item[key] for key in item if key not in {"archive", "message_key", "sequence"}},
                    "sender_hash": "",
                    "recipient_hash": "",
                    "received_at": datetime(2003, 2, 28, tzinfo=UTC),
                    "dataset": "spamassassin",
                    "date": "2003-02-28",
                    "tenant_id": TENANT,
                }
            )
            count += 1
            if len(rows) == 10_000:
                write_batch(rows, destination, batch)
                rows, batch = [], batch + 1
    write_batch(rows, destination, batch)
    return count


def enron(archive: Path, destination: Path, salt: str, limit: int | None = None) -> int:
    rows: list[dict[str, object]] = []
    batch = 0
    count = 0
    with tarfile.open(archive, "r:gz") as handle:
        for member in handle:
            if not member.isfile():
                continue
            stream = handle.extractfile(member)
            if stream is None:
                continue
            try:
                raw = read_header_block(stream)
                message = BytesHeaderParser(policy=default).parsebytes(raw)
                received = parsedate_to_datetime(str(message.get("Date", "")))
                if received.tzinfo is None:
                    received = received.replace(tzinfo=UTC)
                received = received.astimezone(UTC)
                senders = getaddresses(message.get_all("From", []))
                recipients = getaddresses(message.get_all("To", []) + message.get_all("Cc", []))
                sender = senders[0][1] if senders else "missing"
                recipient = recipients[0][1] if recipients else "missing"
                rows.append(
                    {
                        **header_features(raw),
                        "label": None,
                        "sender_hash": pseudonym(sender, salt),
                        "recipient_hash": pseudonym(recipient, salt),
                        "received_at": received,
                        "dataset": "enron",
                        "date": received.date().isoformat(),
                        "tenant_id": TENANT,
                    }
                )
            except (TypeError, ValueError, OverflowError):
                continue
            count += 1
            if len(rows) == 20_000:
                write_batch(rows, destination, batch)
                rows, batch = [], batch + 1
            if limit is not None and count >= limit:
                break
    write_batch(rows, destination, batch)
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--max-enron", type=int)
    args = parser.parse_args()
    destination = args.data_root / "processed" / "email_metadata_v1"
    salt = os.getenv("OFFLINE_DATASET_SALT", "m365-risk-offline-demo")
    spam_count = spamassassin(args.data_root / "raw" / "spamassassin", destination)
    enron_count = enron(
        args.data_root / "raw" / "enron" / "enron_mail_20150507.tar.gz",
        destination,
        salt,
        args.max_enron,
    )
    print(f"wrote {spam_count:,} SpamAssassin and {enron_count:,} Enron metadata records")


if __name__ == "__main__":
    main()
