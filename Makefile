SHELL := /bin/bash
PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PNPM := ./scripts/pnpm24.sh

.PHONY: install doctor bootstrap lock data train notebooks api-types demo scenario test integration e2e benchmark down reset-demo release-local rollback

install:
	./scripts/install.sh

doctor:
	./scripts/doctor.sh --after-start

bootstrap:
	./scripts/bootstrap.sh

lock:
	CUSTOM_COMPILE_COMMAND="make lock" $(PYTHON) -m piptools compile --generate-hashes --resolver=backtracking --strip-extras --allow-unsafe requirements.in -o requirements.txt
	CUSTOM_COMPILE_COMMAND="make lock" $(PYTHON) -m piptools compile --generate-hashes --resolver=backtracking --strip-extras --allow-unsafe requirements-ml.in -o requirements-ml.txt
	CUSTOM_COMPILE_COMMAND="make lock" $(PYTHON) -m piptools compile --generate-hashes --resolver=backtracking --strip-extras --allow-unsafe requirements-dev.in -o requirements-dev.txt

data:
	./scripts/download_datasets.sh
	$(PYTHON) scripts/generate_synthetic.py
	$(PYTHON) scripts/verify_datasets.py
	$(PYTHON) -m scripts.prepare_datasets

train:
	$(PYTHON) -m packages.ml.m365risk_ml.train --data-root data --output artifacts/models/current

notebooks:
	$(PYTHON) scripts/create_notebooks.py
	mkdir -p reports/generated
	set -euo pipefail; for notebook in notebooks/*.ipynb; do \
	  name=$$(basename "$$notebook"); \
	  $(PYTHON) -m papermill "$$notebook" "reports/generated/$$name" -k python3 -p PROJECT_ROOT "$(CURDIR)"; \
	  $(PYTHON) -m jupyter nbconvert --to html "reports/generated/$$name" --output-dir reports/generated; \
	done

api-types:
	TOKEN_ENCRYPTION_KEY=local-openapi-key-with-at-least-32-characters $(PYTHON) -m scripts.export_openapi
	$(PNPM) --dir apps/web generate:api

demo:
	test -f .env || cp .env.example .env
	@if test -f data/DATASET_MANIFEST.json && \
		$(PYTHON) scripts/verify_datasets.py >/dev/null 2>&1; then \
		echo "Training datasets are present and checksum-verified"; \
	else \
		echo "Full training datasets are optional for the offline simulator; run 'make data' before training"; \
	fi
	$(PYTHON) -m scripts.build_demo_model
	docker compose up --build -d
	./scripts/wait-for-demo.sh

scenario:
	./scripts/scenario.sh "$${NAME:-credential-phishing}"

test:
	$(PYTHON) -m ruff check services packages tests scripts
	$(PYTHON) -m mypy services packages
	$(PYTHON) -m pytest -m "not integration and not e2e" --cov
	$(PNPM) --dir apps/web lint
	$(PNPM) --dir apps/web test

integration:
	docker compose up -d postgres mock-graph
	@for attempt in $$(seq 1 30); do \
	  docker compose exec -T postgres pg_isready -U postgres -d m365risk >/dev/null 2>&1 && break; \
	  test $$attempt -lt 30 || { echo "PostgreSQL did not become ready" >&2; exit 1; }; \
	  sleep 1; \
	done
	DATABASE_ADMIN_URL=postgresql://postgres:postgres@localhost:5432/m365risk $(PYTHON) -m alembic upgrade head
	DATABASE_URL=postgresql+asyncpg://m365risk:m365risk@localhost:5432/m365risk \
	DATABASE_ADMIN_URL=postgresql://postgres:postgres@localhost:5432/m365risk \
	MODEL_DIR=$(CURDIR)/artifacts/models/current $(PYTHON) -m services.api.app.seed
	DATABASE_URL=postgresql+asyncpg://m365risk:m365risk@localhost:5432/m365risk \
	DATABASE_ADMIN_URL=postgresql://postgres:postgres@localhost:5432/m365risk \
	MOCK_GRAPH_URL=http://localhost:8081 OIDC_ISSUER=http://localhost:8081 \
	$(PYTHON) -m pytest -m integration

e2e:
	$(PNPM) --dir apps/web exec playwright test

benchmark:
	$(PYTHON) -m scripts.benchmark
	$(PYTHON) -m scripts.check_compose_memory

down:
	docker compose down

reset-demo:
	docker compose down -v

release-local:
	./scripts/release-local.sh

rollback:
	./scripts/rollback-local.sh
