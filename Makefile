.PHONY: lint test-tier1 test-tier2 test test-tier1-otel test-tier2-otel test-otel clean patch-config help

SHELL := /bin/bash
TIER1_DIR := tests/tier1
TIER1_OTEL_DIR := tests/tier1-otel
TIER2_DIR := tests/tier2/terraform
COMPOSE := docker compose -f $(TIER1_DIR)/docker-compose.yml
COMPOSE_OTEL := docker compose -f $(TIER1_OTEL_DIR)/docker-compose.yml

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Tier 1: Docker-based tests (fast, local)
# ---------------------------------------------------------------------------

lint: ## Validate config.alloy syntax via Alloy container
	@echo "=== Checking config.alloy syntax ==="
	docker run --rm -v $(PWD)/config.alloy:/etc/alloy/config.alloy \
		grafana/alloy:latest fmt /etc/alloy/config.alloy > /dev/null
	@echo "Syntax OK"

patch-config: ## Generate test-patched config for Tier 1
	@echo "=== Patching config for Docker tests ==="
	python3 scripts/patch_config_for_test.py

test-tier1: patch-config ## Run Tier 1 tests in Docker
	@echo "=== Starting Tier 1 test environment ==="
	$(COMPOSE) up -d prometheus fixture-server alloy
	@echo "=== Waiting for Alloy to scrape (this takes ~90s) ==="
	@echo "=== Running tests ==="
	$(COMPOSE) run --rm test-runner; \
		EXIT_CODE=$$?; \
		echo "=== Tearing down ===";\
		$(COMPOSE) down -v; \
		exit $$EXIT_CODE

test: lint test-tier1 ## Run lint + Tier 1 (default CI target)

# ---------------------------------------------------------------------------
# Tier 1 OTEL: Docker-based tests using vanilla otelcol-contrib
# ---------------------------------------------------------------------------

patch-otel-config: ## Generate test-patched OTEL config for Tier 1
	@echo "=== Patching OTEL config for Docker tests ==="
	python3 scripts/patch_otel_config_for_test.py

test-tier1-otel: patch-otel-config ## Run Tier 1 OTEL tests (vanilla otelcol-contrib in Docker)
	@echo "=== Starting OTEL Tier 1 test environment ==="
	$(COMPOSE_OTEL) up -d prometheus otelcol
	@echo "=== Waiting for OTEL collector to push metrics (~90s) ==="
	@echo "=== Running tests ==="
	$(COMPOSE_OTEL) run --rm test-runner; \
		EXIT_CODE=$$?; \
		echo "=== Tearing down ===";\
		$(COMPOSE_OTEL) down -v; \
		exit $$EXIT_CODE

test-otel: test-tier1-otel ## Run OTEL Tier 1 tests

# ---------------------------------------------------------------------------
# Tier 2: GCP VM-based tests (thorough, cross-distro)
# ---------------------------------------------------------------------------

test-tier2: ## Run Tier 2 tests on GCP VMs (requires terraform.tfvars)
	@echo "=== Provisioning GCP VMs ==="
	cd $(TIER2_DIR) && terraform init -input=false && terraform apply -auto-approve
	@echo "=== Waiting for VMs to initialize (5 min for package installs) ==="
	@sleep 300
	@echo "=== Running Tier 2 tests ==="
	cd tests/tier2 && pip install -q -r requirements.txt && \
		python -m pytest -v --tb=short test_runner.py; \
		EXIT_CODE=$$?; \
		echo "=== Tearing down GCP VMs ==="; \
		cd terraform && terraform destroy -auto-approve; \
		exit $$EXIT_CODE

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove all test artifacts and infrastructure
	$(COMPOSE) down -v 2>/dev/null || true
	$(COMPOSE_OTEL) down -v 2>/dev/null || true
	rm -f $(TIER1_DIR)/config.alloy.test
	rm -f $(TIER1_OTEL_DIR)/config-otel.test.yaml
	cd $(TIER2_DIR) && terraform destroy -auto-approve 2>/dev/null || true
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
