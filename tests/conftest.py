from __future__ import annotations

import os

os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "unit-test-master-key-with-at-least-32-characters")
os.environ.setdefault("MOCK_ADMIN_SECRET", "unit-test-mock-admin-secret")
os.environ.setdefault("METRICS_KEY", "unit-test-metrics-key-long-enough")
os.environ["OIDC_ISSUER"] = "http://localhost:8081"
os.environ["APP_ENV"] = "test"
