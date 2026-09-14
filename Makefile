# Pre-push safety net: `make check` runs lint + the full test suite.
.PHONY: check lint test sync-assets ext dev serve parity drill schema-dump

PY ?= .venv/bin/python
FLASK ?= http://127.0.0.1:8099
NEW ?= http://127.0.0.1:8086

check: lint test

lint:
	$(PY) -m ruff check .

test:
	$(PY) -m pytest tests/ -q

# Copy shared frontend assets (web/shared/*) into the relay repo.
sync-assets:
	scripts/sync_shared_assets.sh

# Package browser extensions into static/ext (downloadable from Utilities).
ext:
	scripts/build_extensions.sh

# Development instance beside a live box: other port, scratch DB, no
# workers/integrations, never writes the crontab, own mpv socket prefix.
dev:
	SP_PORT=8086 SP_WORKERS=0 SP_INTEGRATIONS=0 SP_CRON_APPLY=0 \
	SP_MPV_SOCKET_PREFIX=/tmp/mpvsocket-dev- $(PY) ws.py --dev

serve:
	$(PY) ws.py

# GET-parity between a Flask instance and this app on the same DB copy.
parity:
	$(PY) scripts/parity.py --flask $(FLASK) --new $(NEW)

# Schema drill: fresh DB here vs the checked-in Flask schema fixture.
drill:
	$(PY) -m pytest tests/test_schema_parity.py tests/test_migrations.py -q

schema-dump:
	$(PY) scripts/schema_dump.py tests/fixtures/schema_0017.sql
