from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from .config import get_settings
from .database import AdminSessionLocal
from .models import ModelVersion, SyncJob, Tenant

TENANTS = (
    (uuid.UUID("00000000-0000-4000-8000-000000000001"), "Northwind Research"),
    (uuid.UUID("00000000-0000-4000-8000-000000000002"), "Contoso Operations"),
)


async def seed() -> None:
    settings = get_settings()
    manifest_path = Path(settings.model_dir) / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    async with AdminSessionLocal() as session, session.begin():
        for tenant_id, name in TENANTS:
            if not await session.get(Tenant, tenant_id):
                session.add(Tenant(id=tenant_id, name=name))
                await session.flush()
                session.add(SyncJob(tenant_id=tenant_id, checkpoint={}))
            version = str(manifest["version"]) if manifest else "rules-demo"
            model = await session.get(ModelVersion, (tenant_id, version))
            if not model:
                session.add(
                    ModelVersion(
                        tenant_id=tenant_id,
                        version=version,
                        approved=bool(manifest and manifest.get("approved")),
                        feature_version=str(
                            manifest.get("feature_version", "EmailMetadataV1")
                            if manifest
                            else "EmailMetadataV1"
                        ),
                        metrics=dict(manifest.get("metrics", {})) if manifest else {},
                    )
                )
            elif manifest:
                model.approved = bool(manifest.get("approved"))
                model.feature_version = str(
                    manifest.get("feature_version", "EmailMetadataV1")
                )
                model.metrics = dict(manifest.get("metrics", {}))


if __name__ == "__main__":
    asyncio.run(seed())
