# Bylaw Compliance Checker

Check a building design against Pune's building bylaws **while you are still designing it**, from inside Revit or by uploading an IFC file.

Every result names the clause it comes from (UDCPR 2020 or NBC 2016), shows the measured value against the limit, and says how much to change (for example "increase by 0.15 m"). When the model doesn't contain a fact that a rule needs, such as a road width, the checker says it **can't verify** that clause and asks one question, instead of guessing a pass.

Built for the Nebius × NVIDIA Global AI Hackathon (2026), Best Apps and Agents track. Powered by NVIDIA Nemotron models on Nebius Token Factory, with Tavily search running during every check.

> **Disclaimer.** This is a design aid. It covers a subset of the rules, and it does not replace professional review, AutoDCR/BPMS scrutiny, or approval by the planning authority.

## Try it

- **Hosted demo:** _URL added at submission_. Open it and click a sample project; no login is needed.
- **Locally:** see [Run it locally](#run-it-locally) below.

## What it does

| | |
|---|---|
| **Two ways in** | A Revit 2026 add-in (Pair → Site Setup → Run Check) and an IFC upload in the web app. Both produce the same `BuildingModel` JSON ([schemas/](schemas/)). |
| **Deterministic rules** | Each rule is a YAML file: the clause excerpt (copied from the source PDF), plus short expressions in a sandboxed mini-language. Only the rule engine decides pass or fail, never a language model. |
| **Can't verify, not a false pass** | Missing inputs produce a "can't verify" result and a question, ranked by how many checks the answer unlocks. Every fact records where it came from: `model`, `inferred`, `declared` or `default`. |
| **Fix by** | Failures state the change needed in the rule's unit; an FSI card shows used vs permissible FSI and the floor area still buildable. |
| **Results back in the model** | In Revit, a "Compliance Check" 3D view colours failing elements and a docked pane lists issues. For IFC, a 3D viewer in the browser, and a BCF 2.1 export for Solibri, BIMcollab, Archicad or BlenderBIM. |
| **Rules compiled from text** | A rule compiler turns pasted bylaw text into a draft rule, checks it, and has a second model review it. Drafts only go live after a person verifies them. |
| **Fresh rules** | During each check, Tavily searches government sites for notifications that might supersede a rule, and the result is flagged in the report. |
| **Location aware** | The site location selects the planning authority (Pune → UDCPR with NBC as fallback) and the metro TOD zone from OpenStreetMap station data. |

## How Nemotron and Token Factory are used

All model calls go through Nebius Token Factory's OpenAI-compatible API ([backend/src/compliance/llm/](backend/src/compliance/llm/)). Code asks for a **role**; [backend/config/models.yaml](backend/config/models.yaml) maps roles to models.

| Role | Model | Used for |
|---|---|---|
| `fast` | Nemotron 3 Nano | Classifying unnamed rooms, triaging Tavily results for the freshness check, rewording questions |
| `agent` | Nemotron 3 Super | Compiling clause text into rules, writing explanations |
| `reviewer` | Nemotron 3 Ultra | Reviewing compiled rules against the clause text before a person sees them |

Structured output uses JSON Schema (with one repair attempt and a tool-calling fallback). Every call is logged with tokens and latency; the web app's **About** page shows the live totals. Prompts are versioned files in [backend/prompts/](backend/prompts/).

## Architecture

```
Revit add-in (C#, .NET 8) ──PUT model──┐
                                       ▼
Web app (React) ──IFC upload──▶ FastAPI ──▶ job: authority → overlays → classify (Nano)
       ▲                          │          → derive → evaluate (rule engine) → freshness (Tavily + Nano)
       │                          │          → questions (Nano) → explain (Super)
       └──── SSE progress, report, BCF, 3D mesh ◀──┘
                                  │
                       SQLite · rules/*.yaml · schemas/*.json
```

- **Backend:** Python 3.12, FastAPI, IfcOpenShell, shapely, SQLite ([backend/](backend/)).
- **Rule engine:** [engine/expr.py](backend/src/compliance/engine/expr.py) is an AST allow-list evaluator with three-valued logic (no `eval`); [engine/evaluate.py](backend/src/compliance/engine/evaluate.py) is the only place pass/fail is decided.
- **Rules:** [rules/udcpr2020/](rules/udcpr2020/) and the Pune layer [rules/cities/pmc/](rules/cities/pmc/) (TOD); compiler drafts land in [rules/drafts/](rules/drafts/).
- **Web:** Vite, React, TypeScript, Tailwind, Leaflet, three.js ([web/](web/)), styled to the PerSpec UI/UX guidelines (dark, monochrome, one accent; AI-inferred values shown dashed).
- **Revit add-in:** [revit-addin/](revit-addin/). It never modifies model elements; it only writes its own Extensible Storage and the "Compliance Check" view.

## Run it locally

Prerequisites: [uv](https://docs.astral.sh/uv/) (Python 3.12), Node.js 22+, [just](https://github.com/casey/just). For the add-in: .NET 8 SDK and Revit 2026.

1. **Keys.** Copy `.env.example` to `.env` and set `NEBIUS_API_KEY` ([Token Factory](https://tokenfactory.nebius.com/)) and `TAVILY_API_KEY` ([Tavily](https://tavily.com/)). Without them the rule engine still works, but room classification, the freshness check, explanations and the rule compiler are skipped or unavailable.
2. **Install and build.**
   ```sh
   just setup        # backend dependencies
   just build-web    # web app → web/dist
   ```
3. **Run.**
   ```sh
   just dev-backend  # http://127.0.0.1:8000 serves the API and the web app
   ```
   Open http://127.0.0.1:8000, select a sample (or upload an IFC), confirm the location in Pune, and run the check. For web development with hot reload, also run `just dev-web` and open http://localhost:5173.
4. **Revit (optional).** Close Revit, run `just install-addin`, start Revit and choose *Always Load*. In the web app, open **Pair Revit** for a code, then in Revit use *Compliance → Pair*, *Site Setup* and *Run Check*. A release zip with `install.ps1` is built by `just package-addin`.

**Docker:** `docker compose -f deploy/docker-compose.yml up --build` serves the app on port 8000 (with Caddy for HTTPS when `DOMAIN` is set).

### Tests and tools

```sh
just test-backend        # rule engine, agents (mocked), API, IFC/BCF adapters
just test-addin          # Revit add-in core logic (no Revit needed)
just lint
just find-clause "minimum width of stair"   # search the source PDFs (after just extract-sources)
just compile-rule fixtures/clauses/udcpr-9.4.1-wc.txt   # clause text → draft rule
just make-samples        # regenerate the sample IFC files from fixtures/models
```

## Sources and data

- UDCPR 2020 (Maharashtra, consolidated Jan 2025) is the primary rulebook; NBC 2016 is the fallback. Source PDFs are not redistributed: [sources/manifest.yaml](sources/manifest.yaml) lists the documents and, where they are public, their download links.
- Metro stations: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, ODbL. Map tiles: © OpenStreetMap contributors.
- IFC handling uses [IfcOpenShell](https://ifcopenshell.org/) (LGPL-3.0).

## Licence

[Apache License 2.0](LICENSE).
