APP_DIR := grain_scanner
VENV     := $(APP_DIR)/.venv
PYTHON   := $(VENV)/bin/python
PIP      := $(VENV)/bin/pip
UV       := $(VENV)/bin/uvicorn
ST       := $(VENV)/bin/streamlit
PYTEST   := $(VENV)/bin/pytest

.DEFAULT_GOAL := help

# ── Setup ──────────────────────────────────────────────────────────────────────
.PHONY: install
install: ## Create venv and install all dependencies
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r $(APP_DIR)/requirements.txt
	@echo "✅ Dependencies installed"

.PHONY: env
env: ## Copy .env.example → .env (skips if .env already exists)
	@test -f $(APP_DIR)/.env || cp $(APP_DIR)/.env.example $(APP_DIR)/.env && echo "✅ .env created" || echo "ℹ️  .env already exists"

# ── Run ────────────────────────────────────────────────────────────────────────
.PHONY: api
api: ## Start FastAPI backend (hot-reload)
	cd $(APP_DIR) && ../$(UV) main:app --reload --host 0.0.0.0 --port 8000

.PHONY: ui
ui: ## Start Streamlit dashboard
	cd $(APP_DIR) && ../$(ST) run streamlit_app.py --server.port 8501

PID_FILE := .pids

.PHONY: up
up: ## Start API (:8000) + UI (:8501) in background — use 'make down' to stop
	@[ ! -f $(PID_FILE) ] || { echo "⚠️  Already running. Run 'make down' first."; exit 1; }
	@mkdir -p $(APP_DIR)/logs
	@(cd $(APP_DIR) && .venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000 >> logs/api.log 2>&1) & echo $$! > $(PID_FILE)
	@(cd $(APP_DIR) && .venv/bin/streamlit run streamlit_app.py --server.port 8501 --server.headless true >> logs/ui.log 2>&1) & echo $$! >> $(PID_FILE)
	@echo "✅ API  → http://localhost:8000  (logs: $(APP_DIR)/logs/api.log)"
	@echo "✅ UI   → http://localhost:8501  (logs: $(APP_DIR)/logs/ui.log)"
	@echo "   Docs → http://localhost:8000/docs"
	@echo "   Stop → make down | Logs → make logs"

.PHONY: down
down: ## Stop API + UI started by 'make up'
	@[ -f $(PID_FILE) ] \
	  && { xargs kill 2>/dev/null < $(PID_FILE) || true; rm -f $(PID_FILE); echo "✅ Down"; } \
	  || echo "ℹ️  Nothing running."

.PHONY: logs
logs: ## Tail both API and UI logs
	@tail -f $(APP_DIR)/logs/api.log $(APP_DIR)/logs/ui.log

.PHONY: dev
dev: up ## Alias for up

# ── Tests ─────────────────────────────────────────────────────────────────────
.PHONY: test
test: ## Run full test suite
	cd $(APP_DIR) && ../$(PYTEST) tests/ -v --tb=short

.PHONY: test-fast
test-fast: ## Run tests without slow segmentation tests
	cd $(APP_DIR) && ../$(PYTEST) tests/ -v --tb=short -k "not pipeline"

.PHONY: coverage
coverage: ## Run tests with coverage report
	cd $(APP_DIR) && ../$(PYTEST) tests/ --cov=app --cov-report=term-missing --cov-report=html

# ── Packaging / Licensing ──────────────────────────────────────────────────────
LICENSE_SERVER ?= https://grain-scanner-license.up.railway.app

.PHONY: keygen
keygen: ## Generate a new Ed25519 license keypair (one-time; store private key safely)
	$(PYTHON) packaging/keygen.py --generate-keys

.PHONY: license
license: ## Issue a license key manually:  make license MID=<machine-id>
	$(PYTHON) packaging/keygen.py --machine-id "$(MID)" --private-key "$(GRAIN_SCANNER_PRIVATE_KEY)"

.PHONY: coupon
coupon: ## Create N coupon codes on the license server:  make coupon N=5  (default N=1)
	curl -s -X POST "$(LICENSE_SERVER)/admin/coupons" \
	  -H "Content-Type: application/json" \
	  -H "X-Admin-Key: $(GRAIN_SCANNER_ADMIN_KEY)" \
	  -d "{\"count\": $(or $(N),1), \"max_uses\": 1}" | python3 -m json.tool

.PHONY: coupons
coupons: ## List all coupons and their usage
	curl -s "$(LICENSE_SERVER)/admin/coupons" \
	  -H "X-Admin-Key: $(GRAIN_SCANNER_ADMIN_KEY)" | python3 -m json.tool

# ── Docker ─────────────────────────────────────────────────────────────────────
.PHONY: docker-build
docker-build: ## Build Docker image
	cd $(APP_DIR) && docker build -t grain-scanner:latest .

.PHONY: docker-up
docker-up: ## Start API + UI via docker-compose
	cd $(APP_DIR) && docker-compose up --build

.PHONY: docker-down
docker-down: ## Stop docker-compose services
	cd $(APP_DIR) && docker-compose down

# ── Maintenance ────────────────────────────────────────────────────────────────
.PHONY: clean
clean: ## Remove venv, cache, outputs, db
	rm -rf $(VENV) $(APP_DIR)/__pycache__ $(APP_DIR)/**/__pycache__
	rm -rf $(APP_DIR)/.pytest_cache $(APP_DIR)/htmlcov
	rm -f $(APP_DIR)/grain_scanner.db
	rm -rf $(APP_DIR)/outputs/* $(APP_DIR)/data/uploads/* $(APP_DIR)/logs/*
	@echo "✅ Clean"

.PHONY: lint
lint: ## Run ruff linter
	$(VENV)/bin/ruff check $(APP_DIR)/app $(APP_DIR)/tests

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*##"}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
