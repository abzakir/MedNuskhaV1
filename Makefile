# MedNuskha — AGENTS.md §7.
#
# This Makefile is the canonical target set (dev / test / seed) and is what runs
# on the Alibaba Cloud ECS box in Phase 8. On Windows dev machines `make` is not
# installed; use the equivalent PowerShell shims instead:
#     ./dev.ps1    ./test.ps1    ./seed.ps1    ./install.ps1

.PHONY: install dev backend frontend test seed clean

VENV     := backend/.venv
VENV_BIN := $(VENV)/bin
PYTHON   ?= python3

install:
	$(PYTHON) -m venv $(VENV)
	$(VENV_BIN)/pip install --upgrade pip
	$(VENV_BIN)/pip install -r backend/requirements.txt
	cd frontend && npm install

# Runs the FastAPI backend on :8000 and the Next.js dashboard on :3000.
# Ctrl-C stops both.
dev:
	@echo "backend  -> http://localhost:8000  (health: /api/health)"
	@echo "frontend -> http://localhost:3000"
	@trap 'kill 0' INT TERM; \
	$(VENV_BIN)/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload & \
	(cd frontend && npm run dev) & \
	wait

backend:
	$(VENV_BIN)/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload

frontend:
	cd frontend && npm run dev

test:
	cd backend && ../$(VENV_BIN)/pytest -q

seed:
	$(VENV_BIN)/python scripts/seed_demo.py

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache frontend/.next
