.PHONY: dashboard dev build install help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install Python + Node dependencies
	.venv/bin/pip install -q fastapi 'uvicorn[standard]' websockets httpx pyyaml rich
	cd dashboard && npm install

build: ## Build React frontend for production
	cd dashboard && npm run build

dashboard: build ## Build and launch the production dashboard
	.venv/bin/python -m harness.cli --dashboard

dev: ## Run FastAPI backend + Vite dev server (hot reload)
	@echo "Starting dev environment..."
	@echo "  Backend:  http://localhost:5174"
	@echo "  Frontend: http://localhost:5173"
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend: ## Run FastAPI on port 5174
	.venv/bin/python -m harness.cli --dashboard --port 5174

dev-frontend: ## Run Vite dev server on port 5173 (proxies API to 5174)
	cd dashboard && npm run dev -- --port 5173

clean: ## Remove build artifacts
	rm -rf dashboard/dist
