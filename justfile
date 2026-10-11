# All project commands. `just --list` to see them. (P0.7)
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

py := "uv run --project backend python"

default:
    @just --list

# Install backend dependencies (web/ is added in P6.3)
setup:
    uv sync --project backend

# Generate Python/TS/C# types from schemas/ (P1.5)
codegen:
    @just _todo P1.5

# Export OpenAPI and generate the web API client (P4.5)
codegen-api:
    @just _todo P4.5

# Validate one JSON file against its schema (P1.6)
validate file:
    @just _todo P1.6

# Validate every fixture in fixtures/models (P1.6)
validate-fixtures:
    @just _todo P1.6

# Run backend tests; extra args go to pytest, e.g. `just test-backend -k expr`
[working-directory: 'backend']
test-backend *args:
    uv run pytest -q {{args}}

# Lint the backend
[working-directory: 'backend']
lint:
    uv run ruff check

# Run the API locally (P4.2)
dev-backend:
    @just _todo P4.2

# Run the web app locally (P6.3)
dev-web:
    @just _todo P6.3

# Build the web app (P6.3)
build-web:
    @just _todo P6.3

# Build the Revit add-in (P5.1)
build-addin:
    @just _todo P5.1

# Check the Nemotron models on Nebius; add --write to update backend/config/models.yaml (P0.5)
smoke-llm *args:
    {{py}} scripts/smoke_nebius.py {{args}}

# Check Tavily search and extract against government domains (P0.6)
smoke-tavily:
    {{py}} scripts/smoke_tavily.py

# Compile a clause text file into a draft rule (P3.5)
compile-rule file:
    @just _todo P3.5

# Extract source PDFs page by page and build the clause search index (P0.9)
extract-sources *args:
    {{py}} scripts/extract_sources.py {{args}}

# Search the source documents, e.g. `just find-clause "minimum width of stair"` (P0.9)
find-clause query:
    {{py}} scripts/extract_sources.py find "{{query}}"

# Fetch Pune metro stations from OpenStreetMap (P3.10)
fetch-stations:
    @just _todo P3.10

_todo task:
    @echo "not yet implemented ({{task}})"
    @exit 1
