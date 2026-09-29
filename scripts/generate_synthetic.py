#!/usr/bin/env python3
"""Generate privacy-safe Microsoft 365 user-risk and phishing scenario data.

Only metadata and derived features are emitted. No message body, preview, or
attachment content is generated or stored.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

RISK_LEVELS = ("none", "low", "medium", "high")
DAILY_FIELDS = (
    "tenant_id",
    "user_id",
    "date",
    "emails_received",
    "external_sender_ratio",
    "suspicious_header_count",
    "sender_domain_novelty",
    "email_risk_mean",
    "email_risk_max",
    "is_mfa_registered",
    "is_mfa_capable",
    "is_admin",
    "entra_risk_level",
    "behaviour_anomaly_score",
    "label",
)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class UserProfile:
    tenant_id: str
    user_id: str
    baseline_messages: float
    baseline_external: float
    is_mfa_registered: bool
    is_mfa_capable: bool
    is_admin: bool
    attack_start: int | None
    attack_length: int


def build_profiles(args: argparse.Namespace, rng: random.Random) -> list[UserProfile]:
    profiles: list[UserProfile] = []
    for tenant_number in range(1, args.tenants + 1):
        tenant_id = f"tenant-{tenant_number:03d}"
        for user_number in range(1, args.users_per_tenant + 1):
            attacked = rng.random() < args.compromise_rate
            attack_length = rng.randint(2, min(14, max(2, args.days))) if attacked else 0
            attack_start = (
                rng.randint(0, max(0, args.days - attack_length)) if attacked else None
            )
            is_admin = rng.random() < 0.06
            mfa_registered = rng.random() < (0.96 if is_admin else 0.86)
            profiles.append(
                UserProfile(
                    tenant_id=tenant_id,
                    user_id=f"user-{user_number:05d}",
                    baseline_messages=max(2.0, rng.lognormvariate(math.log(28), 0.45)),
                    baseline_external=clamp(rng.betavariate(2.2, 6.0), 0.02, 0.80),
                    is_mfa_registered=mfa_registered,
                    is_mfa_capable=mfa_registered or rng.random() < 0.75,
                    is_admin=is_admin,
                    attack_start=attack_start,
                    attack_length=attack_length,
                )
            )
    return profiles


def daily_row(
    profile: UserProfile, day_index: int, current_date: date, rng: random.Random
) -> dict[str, object]:
    compromised = (
        profile.attack_start is not None
        and profile.attack_start <= day_index < profile.attack_start + profile.attack_length
    )
    weekend_factor = 0.35 if current_date.weekday() >= 5 else 1.0
    messages = max(
        0,
        round(
            rng.gauss(profile.baseline_messages * weekend_factor, 4.0)
            * (1.65 if compromised else 1.0)
        ),
    )
    external = clamp(
        rng.gauss(profile.baseline_external + (0.28 if compromised else 0.0), 0.05)
    )
    novelty = clamp(rng.betavariate(2, 11) + (0.45 if compromised else 0.0))
    suspicious = max(
        0,
        round(rng.gauss(0.12 + messages * 0.006 + (4.0 if compromised else 0.0), 0.8)),
    )
    email_mean = clamp(
        0.025 + external * 0.10 + novelty * 0.18 + suspicious * 0.045
        + rng.gauss(0, 0.025)
    )
    email_max = clamp(email_mean + rng.betavariate(1.5, 4.5) + (0.25 if compromised else 0))
    anomaly = clamp(
        abs(messages - profile.baseline_messages * weekend_factor)
        / max(8.0, profile.baseline_messages * 1.8)
        + max(0.0, external - profile.baseline_external) * 0.8
        + novelty * 0.35
    )

    posture = 0.0 if profile.is_mfa_registered else 0.65
    privilege = 0.55 if profile.is_admin else 0.08
    latent_risk = 0.35 * email_max + 0.20 * anomaly + 0.15 * posture + 0.10 * privilege
    if compromised:
        latent_risk += 0.35
    if latent_risk >= 0.82:
        entra = "high"
    elif latent_risk >= 0.58:
        entra = "medium"
    elif latent_risk >= 0.33:
        entra = "low"
    else:
        entra = "none"

    return {
        "tenant_id": profile.tenant_id,
        "user_id": profile.user_id,
        "date": current_date.isoformat(),
        "emails_received": messages,
        "external_sender_ratio": f"{external:.4f}",
        "suspicious_header_count": suspicious,
        "sender_domain_novelty": f"{novelty:.4f}",
        "email_risk_mean": f"{email_mean:.4f}",
        "email_risk_max": f"{email_max:.4f}",
        "is_mfa_registered": str(profile.is_mfa_registered).lower(),
        "is_mfa_capable": str(profile.is_mfa_capable).lower(),
        "is_admin": str(profile.is_admin).lower(),
        "entra_risk_level": entra,
        "behaviour_anomaly_score": f"{anomaly:.4f}",
        "label": int(compromised),
    }


def write_daily_data(
    output: Path,
    profiles: list[UserProfile],
    start_date: date,
    days: int,
    rng: random.Random,
) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with output.open("wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0
    ) as compressed, io.TextIOWrapper(compressed, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DAILY_FIELDS)
        writer.writeheader()
        for day_index in range(days):
            current_date = start_date + timedelta(days=day_index)
            for profile in profiles:
                writer.writerow(daily_row(profile, day_index, current_date, rng))
                rows += 1
    return rows


def write_campaigns(
    output: Path,
    tenants: int,
    campaign_count: int,
    start_date: date,
    days: int,
    rng: random.Random,
) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    events = 0
    domains = ("secure-share.example", "m365-alert.example", "invoice-review.example")
    with output.open("wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0
    ) as compressed, io.TextIOWrapper(compressed, encoding="utf-8") as handle:
        for campaign_number in range(1, campaign_count + 1):
            tenant = rng.randint(1, tenants)
            event_count = rng.randint(30, 150)
            start = datetime.combine(
                start_date + timedelta(days=rng.randrange(days)),
                time(hour=rng.randint(6, 21), minute=rng.randint(0, 59)),
                tzinfo=UTC,
            )
            for event_number in range(event_count):
                event = {
                    "campaign_id": f"campaign-{campaign_number:04d}",
                    "tenant_id": f"tenant-{tenant:03d}",
                    "event_id": f"event-{event_number + 1:05d}",
                    "received_at": (start + timedelta(seconds=event_number * rng.randint(8, 45))).isoformat(),
                    "sender_domain": rng.choice(domains),
                    "recipient_count": rng.randint(1, 4),
                    "external_sender": True,
                    "spf_result": rng.choice(("fail", "softfail", "none")),
                    "dkim_result": rng.choice(("fail", "none")),
                    "dmarc_result": rng.choice(("fail", "none")),
                    "reply_to_domain_mismatch": rng.random() < 0.78,
                    "from_sender_mismatch": rng.random() < 0.42,
                    "received_hops": rng.randint(2, 9),
                    "has_attachments": rng.random() < 0.33,
                    "label": 1,
                }
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
                events += 1
    return events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenants", type=int, default=5)
    parser.add_argument("--users-per-tenant", type=int, default=200)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--compromise-rate", type=float, default=0.035)
    parser.add_argument("--campaigns", type=int, default=25)
    parser.add_argument("--seed", type=int, default=365)
    parser.add_argument(
        "--daily-output",
        type=Path,
        default=Path("data/synthetic/m365_user_daily.csv.gz"),
    )
    parser.add_argument(
        "--campaign-output",
        type=Path,
        default=Path("data/synthetic/phishing_campaigns.jsonl.gz"),
    )
    args = parser.parse_args()
    if args.tenants < 1 or args.users_per_tenant < 1 or args.days < 2:
        parser.error("tenants/users-per-tenant must be >= 1 and days must be >= 2")
    if not 0 <= args.compromise_rate <= 1:
        parser.error("compromise-rate must be between 0 and 1")
    return args


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    profiles = build_profiles(args, rng)
    rows = write_daily_data(args.daily_output, profiles, args.start_date, args.days, rng)
    events = write_campaigns(
        args.campaign_output,
        args.tenants,
        args.campaigns,
        args.start_date,
        args.days,
        rng,
    )
    print(f"wrote {rows:,} daily rows to {args.daily_output}")
    print(f"wrote {events:,} campaign events to {args.campaign_output}")


if __name__ == "__main__":
    main()
