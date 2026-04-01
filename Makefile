.PHONY: install dev backend frontend auth download features train bot test stop clean \
	deploy-auth deploy-redeploy deploy-logs deploy-health deploy-status deploy-ssh

# =============================================================================
# Setup
# =============================================================================

install: ## Install all dependencies (backend + frontend)
	cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	cd frontend && bun install

# =============================================================================
# Development
# =============================================================================

dev: ## Start both backend and frontend
	@echo "Starting backend on :8000 and frontend on :3000"
	@make backend & make frontend

backend: ## Start backend API server
	. backend/.venv/bin/activate && uvicorn backend.main:app --reload --port 8000

frontend: ## Start frontend dev server
	cd frontend && bun run dev

# =============================================================================
# Trading Operations
# =============================================================================

auth: ## Authenticate with Zerodha (daily)
	. backend/.venv/bin/activate && python3 backend/scripts/auth.py

download: ## Download historical market data
	. backend/.venv/bin/activate && python3 backend/scripts/download_data.py

features: ## Generate ML features from historical data
	. backend/.venv/bin/activate && python3 backend/scripts/generate_features.py

train: ## Train ML model (with 45-day decay)
	. backend/.venv/bin/activate && python3 backend/scripts/train.py --half-life 45

bot: ## Run trading bot (paper mode)
	. backend/.venv/bin/activate && python3 backend/scripts/run_bot.py

reversal: ## Run daily reversal strategy (pseudo trading)
	. backend/.venv/bin/activate && python3 backend/scripts/run_reversal.py

reversal-status: ## Check reversal strategy status
	. backend/.venv/bin/activate && python3 backend/scripts/run_reversal.py --status

reversal-reset: ## Reset reversal strategy state
	. backend/.venv/bin/activate && python3 backend/scripts/run_reversal.py --reset

intraday: ## Run intraday entry filter on reversal picks (live monitoring)
	. backend/.venv/bin/activate && python3 backend/scripts/run_intraday_reversal.py

intraday-scan: ## Single scan of intraday entries (no loop)
	. backend/.venv/bin/activate && python3 backend/scripts/run_intraday_reversal.py --scan

bot-test: ## Run single test cycle
	. backend/.venv/bin/activate && python3 backend/scripts/run_bot.py --test

backtest: ## Run backtest (long + short)
	. backend/.venv/bin/activate && python3 backend/scripts/backtest.py

backtest-compare: ## Run backtest comparing long-only vs long+short
	. backend/.venv/bin/activate && python3 backend/scripts/backtest.py --compare

backtest-long: ## Run backtest (long only)
	. backend/.venv/bin/activate && python3 backend/scripts/backtest.py --long-only

sweep: ## Run TP/SL parameter sweep
	. backend/.venv/bin/activate && python3 backend/scripts/sweep.py

robustness: ## Run rolling window robustness test
	. backend/.venv/bin/activate && python3 backend/scripts/robustness.py

# =============================================================================
# VPS Deployment (run from local machine)
# =============================================================================

VPS_HOST = sarthaktrader
VPS_CONTAINER = trader
VPS_APP_PORT = 8000
VPS_DOMAIN = api.trader.sarthakb.xyz

deploy-auth: auth ## Authenticate locally, copy session to VPS, connect broker, start bot
	scp .kite_session $(VPS_HOST):~/kite_session
	ssh $(VPS_HOST) "docker cp ~/kite_session $(VPS_CONTAINER):/app/.kite_session && rm ~/kite_session"
	ssh $(VPS_HOST) "docker restart $(VPS_CONTAINER)"
	@echo "Waiting for container to start..."
	@sleep 4
	ssh $(VPS_HOST) "curl -sf -X POST http://localhost:$(VPS_APP_PORT)/api/v1/auth/connect"
	@echo ""
	@echo "=== Starting Bot ==="
	ssh $(VPS_HOST) "curl -sf -X POST http://localhost:$(VPS_APP_PORT)/api/v1/bot/start -H 'Content-Type: application/json' -d '{}'"
	@echo ""
	@echo "=== Health Check ==="
	ssh $(VPS_HOST) "curl -sf http://localhost:$(VPS_APP_PORT)/api/v1/health | python3 -m json.tool"

deploy-redeploy: ## Pull latest image and restart container on VPS
	ssh $(VPS_HOST) "~/apps/trader/redeploy.sh"

deploy-health: ## Check VPS backend health
	@curl -sf https://$(VPS_DOMAIN)/api/v1/health | python3 -m json.tool

deploy-status: ## Check VPS container status
	ssh $(VPS_HOST) "docker ps --filter name=$(VPS_CONTAINER)"

deploy-logs: ## Tail VPS container logs
	ssh $(VPS_HOST) "docker logs -f $(VPS_CONTAINER)"

deploy-ssh: ## SSH into VPS
	ssh $(VPS_HOST)

# =============================================================================
# Build & Clean
# =============================================================================

build: ## Build frontend for production
	cd frontend && bun run build

start: ## Start production frontend
	cd frontend && bun run start

clean: ## Clean build artifacts
	rm -rf frontend/.next frontend/node_modules backend/.venv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
