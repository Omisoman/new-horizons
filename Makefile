# new-horizons — one Makefile, all entry points.
# Never run `make demo1` and sojourner' tier stack together (16 GB budget).

SHELL := /bin/zsh
UV    ?= uv
PKG   := src/new_horizons
COMPOSE := docker compose -f docker-compose.yml

MODELS := qwen3:8b llama3.1:8b deepseek-r1:8b qwen3-vl:4b bge-m3

.PHONY: models db-up db-down mock kb ingest demo1 host llm-target test lint client-free audit-rotate marks

## Pull every model the app uses (~20 GB total, one-time).
models:
	@for m in $(MODELS); do echo "== ollama pull $$m"; ollama pull $$m; done
	@ollama list

## Postgres 16 (the five farm systems + the audit chain + the checkpointer).
db-up:
	$(COMPOSE) up -d postgres
	@until docker exec horizons-postgres pg_isready -U horizons -q; do sleep 1; done
	@echo "postgres ready on port $${POSTGRES_PORT:-5432}"

db-down:
	$(COMPOSE) down

## Five synthetic farm databases (telemetry, controller, maintenance, harvest,
## supplies; seeded) + analytics artifacts + the sample scans (data/samples/).
## Scale, period and seed come from src/new_horizons/app/profile.yaml.
mock:
	$(UV) run python -m new_horizons.app.mock.generate
	@for a in drift patterns recon; do \
	  $(UV) run python -m new_horizons.app.analytics.$$a > /dev/null && echo "  analytics: $$a"; done
	$(UV) run python -m new_horizons.app.intake.samples

## Knowledge base: the Farm's corpus -> bge-m3 -> Chroma in data/kb/ (~5 s).
kb:
	$(UV) run python -m new_horizons.app.ingest.run

ingest: kb

## The analytics agent (needs warm Ollama + db-up).
demo1:
	$(UV) run streamlit run $(PKG)/app/app.py --server.headless true

## App-agent host: every app agent in host/registry.yaml in one shell (:8502).
host:
	$(UV) run streamlit run $(PKG)/host/app.py --server.headless true --server.port 8502

## Point every surface at one inference lane: local | rented | claude | hybrid.
##   make llm-target MODE=rented URL=http://gpu-box:8000/v1 MODEL=qwen3-coder:30b
## Embeddings (bge-m3) and the vision model stay local in every lane.
llm-target:
	bash scripts/llm-target.sh $(MODE) $(URL) $(MODEL)

## Unit + integration tests (needs db-up for the audit chain; mock + kb for the farm tests).
test:
	$(UV) run pytest -q

## Architecture contracts: shared never imports the app; views never import each other.
lint:
	$(UV) run lint-imports

## No client vocabulary anywhere in the repository (CI runs the same check). Each word
## carries a one-letter class so the pattern never matches its own definition. LICENSE
## is the verbatim MIT text (its warranty clause trips the check) — legal text, not ours.
CLIENT_WORDS := j[i]co|jerusal[e]m|القد[س]|ins[u]r|cl[a]im|pol[i]cy|gar[a]ge|adjust[e]r|IB[A]N|tar[i]ff|J[O]D
client-free:
	@! grep -rIinE "$(CLIENT_WORDS)" --exclude-dir=node_modules --exclude-dir=.venv \
	  --exclude-dir=data --exclude-dir=dist --exclude-dir=.git --exclude=LICENSE . \
	  && echo "client-free: ok"

## Product marks (assets/brand, footer) from the pixel bitmaps in scripts/brand-marks.py.
marks:
	$(UV) run python scripts/brand-marks.py

## Rotate the audit chain (needs make db-up): the table is archived intact as
## audit_log_archive_<YYYYMMDD>, a new chain starts anchored to it. Never a reset.
##   make audit-rotate REASON="why"
audit-rotate:
	@test -n "$(REASON)" || { echo 'usage: make audit-rotate REASON="why the chain is rotated"'; exit 2; }
	$(UV) run python -m new_horizons.shared.audit.rotate --reason "$(REASON)"
