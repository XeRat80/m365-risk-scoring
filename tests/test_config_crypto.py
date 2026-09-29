from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag
from pydantic import ValidationError

from services.api.app.config import DEFAULT_TOKEN_ENCRYPTION_KEY, Settings
from services.api.app.crypto import SecretCipher


def test_connector_secret_encryption_is_tenant_bound() -> None:
    cipher = SecretCipher("a-production-master-key-that-is-long-enough")
    encrypted = cipher.encrypt("client-secret", "tenant-a")
    assert "client-secret" not in encrypted
    assert cipher.decrypt(encrypted, "tenant-a") == "client-secret"
    with pytest.raises(InvalidTag):
        cipher.decrypt(encrypted, "tenant-b")


def test_production_rejects_mock_connector_and_default_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            connector_mode="mock",
            token_encryption_key="a-production-master-key-that-is-long-enough",  # noqa: S106
        )


def test_production_requires_unique_keys_and_graph_credentials() -> None:
    with pytest.raises(ValidationError, match="default encryption"):
        Settings(
            app_env="production",
            connector_mode="real",
            token_encryption_key=DEFAULT_TOKEN_ENCRYPTION_KEY,
            pseudonymization_key="unique-production-pseudonym-key-long-enough",  # noqa: S106
            mock_admin_secret="secure-production-mock-boundary-secret",  # noqa: S106
            metrics_key="secure-production-metrics-key-long-enough",
            graph_client_id="client",
            graph_client_secret="secret",  # noqa: S106
        )
    with pytest.raises(ValidationError, match="Graph application credentials"):
        Settings(
            app_env="production",
            connector_mode="real",
            token_encryption_key="unique-production-key-with-at-least-32-characters",  # noqa: S106
            pseudonymization_key="unique-production-pseudonym-key-long-enough",  # noqa: S106
            mock_admin_secret="secure-production-mock-boundary-secret",  # noqa: S106
            metrics_key="secure-production-metrics-key-long-enough",
        )
