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
    {{py}} scripts/codegen.py

# Export OpenAPI and generate the web API client (P4.5)
codegen-api:
    {{py}} scripts/export_openapi.py
    cd web; npx openapi-typescript ../schemas/openapi.json -o src/generated/api.ts

# Validate one JSON file against its schema (P1.6)
validate file:
    {{py}} scripts/validate.py "{{file}}"

# Validate every fixture in fixtures/models (P1.6)
validate-fixtures:
    {{py}} scripts/validate.py --fixtures

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
    uv run --project backend uvicorn --factory compliance.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir backend/src

# Print a 6-digit pairing code from the running backend (until the web app shows one, P6)
pair-code url="http://127.0.0.1:8000":
    {{py}} -c "import httpx; print('Pairing code:', httpx.post('{{url}}/api/pair/start').json()['code'], '(valid 10 minutes)')"

# Run the web app locally (P6.3)
dev-web:
    cd web; npm run dev

# Build the web app (P6.3)
build-web:
    cd web; npm ci --no-audit --no-fund; npm run build

# Build the Revit add-in (P5.1)
build-addin:
    dotnet build revit-addin/ComplianceChecker.sln -c Release -nologo -v q

# Run the add-in's Core unit tests (no Revit needed)
test-addin:
    dotnet test revit-addin/tests/ComplianceChecker.Core.Tests -nologo -v q
    {{py}} scripts/validate.py revit-addin/tests/out/sample_export.json

# Build the release zip dist/ComplianceChecker-<version>.zip (P5.10)
package-addin: build-addin
    powershell -NoProfile -ExecutionPolicy Bypass -File revit-addin/install/package.ps1

# Build and install the add-in into %AppData%/Autodesk/Revit/Addins/2026 (close Revit first)
install-addin: build-addin
    powershell -NoProfile -ExecutionPolicy Bypass -File revit-addin/install/install.ps1

# Check the Nemotron models on Nebius; add --write to update backend/config/models.yaml (P0.5)
smoke-llm *args:
    {{py}} scripts/smoke_nebius.py {{args}}

# Check Tavily search and extract against government domains (P0.6)
smoke-tavily:
    {{py}} scripts/smoke_tavily.py

# Compile a clause text file into a draft rule (P3.5)
compile-rule file *args:
    {{py}} scripts/compile_rule.py "{{file}}" {{args}}

# Extract source PDFs page by page and build the clause search index (P0.9)
extract-sources *args:
    {{py}} scripts/extract_sources.py {{args}}

# Search the source documents, e.g. `just find-clause "minimum width of stair"` (P0.9)
find-clause query:
    {{py}} scripts/extract_sources.py find "{{query}}"

# Generate the sample IFC files from the fixture buildings (P6.1)
make-samples:
    {{py}} scripts/make_sample_ifc.py

# Fetch Pune metro stations from OpenStreetMap (P3.10)
fetch-stations *args:
    {{py}} scripts/fetch_metro_stations.py {{args}}

_todo task:
    @echo "not yet implemented ({{task}})"
    @exit 1
