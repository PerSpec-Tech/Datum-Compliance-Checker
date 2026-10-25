# Bylaw Compliance Checker

Check a building design against Pune's building bylaws **while you are still designing it**: inside Revit, inside AutoCAD, or by uploading an IFC model or a DXF drawing to the web app.

Every result names the clause it comes from (UDCPR 2020 or NBC 2016), shows the measured value against the limit, and says how much to change (for example "increase by 0.15 m"). When the design doesn't contain a fact that a rule needs, such as the Development Plan width of the road, the checker says it **can't verify** that clause and asks one question, instead of guessing a pass.

Built by [PerSpec](https://getperspec.com) for the Nebius × NVIDIA Global AI Hackathon (2026), Best Apps and Agents track. Powered by NVIDIA Nemotron models on Nebius Token Factory, with Tavily search running during every check.

> **Disclaimer.** This is a design aid. It covers a subset of the rules, and it does not replace professional review, AutoDCR/BPMS scrutiny, or approval by the planning authority.

## Try it

- **Hosted app: <https://compliance.getperspec.com>.** No login. Click **mixed-use tower near a metro station** (a G+11 IFC building; 10 issues, including the height on a 10.5 m road) or **two-storey bungalow** (a 2D PreDCR-layered DXF; set the site on the map, then 2 issues).
- **Revit 2026 and AutoCAD 2026 plug-ins:** download them from **pair Revit · AutoCAD** in the app. They connect to the hosted app by default.
- **Locally:** see [Run it locally](#run-it-locally).

## What it does

| | |
|---|---|
| **Four ways in** | A Revit 2026 add-in, an AutoCAD 2026 plug-in, and IFC or DXF upload in the web app. All of them produce the same `BuildingModel` JSON ([schemas/](schemas/)), so they agree on every result. |
| **Deterministic rules** | Each rule is a YAML file: the clause excerpt (copied from the source PDF, with its page), plus short expressions in a sandboxed mini-language. Only the rule engine decides pass or fail, never a language model. |
| **Can't verify, not a false pass** | Missing inputs produce a "can't verify" result and a question, ranked by how many checks the answer unlocks. Every fact records where it came from: `model`, `inferred`, `declared` or `default`. |
| **Fix by** | Failures state the change needed in the rule's unit; an FSI card shows used vs permissible FSI and the floor area still buildable. |
| **Results where the design is** | Revit: a "Compliance Check" 3D view colours failing elements, with a docked issue list. AutoCAD: revision clouds and labels on their own `COMPLIANCE ISSUES` layer, and an issue palette that zooms to each one. Web: a full-screen 2D/3D workspace with the setback envelope, a printable report, and BCF 2.1 export for Solibri, BIMcollab, Archicad or BlenderBIM. |
| **Live preview** | In Revit, margins, FSI and height update as you model, from a "live pack" the server compiles from the same rules (the full check stays the official result). |
| **2D drawings** | DXF on PreDCR layers (the layer standard Maharashtra's AutoDCR expects), or any layering after a one-time layer review that Nemotron pre-fills. Floors drawn side by side in one file are aligned on their stair/lift core. |
| **Site setup** | Place the plot on a map, tag road and neighbour sides, set road widths; in AutoCAD this happens inside the drawing. The location selects the planning authority (Pune → UDCPR with NBC as fallback), the metro TOD zone and the congested-area rules, with land use suggested from OpenStreetMap. |
| **Rules compiled from text** | A rule compiler turns pasted bylaw text into a draft rule, checks it deterministically, and has a second model review it. Drafts only go live after a person verifies them. |
| **Fresh rules** | During each check, Tavily searches government sites for notifications that might supersede a rule, and the result is flagged in the report. |

## How Nemotron and Token Factory are used

All model calls go through Nebius Token Factory's OpenAI-compatible API ([backend/src/compliance/llm/](backend/src/compliance/llm/)). Code asks for a **role**; [backend/config/models.yaml](backend/config/models.yaml) maps roles to models.

| Role | Model | Used for |
|---|---|---|
| `fast` | Nemotron 3 Nano | Classifying rooms with unrecognised names, suggesting what each DXF layer is, triaging Tavily results for the freshness check, rewording questions |
| `agent` | Nemotron 3 Super | Compiling clause text into rules, writing plain-language explanations |
| `reviewer` | Nemotron 3 Ultra | Reviewing compiled rules against the clause text before a person sees them |

Structured output uses JSON Schema (with one repair attempt and a tool-calling fallback), and reasoning is switched on or off per call. Every call is logged with tokens and latency; the app's **About** page shows the live totals. Prompts are versioned files in [backend/prompts/](backend/prompts/).

## Architecture

```
Revit add-in (C#) ───── BuildingModel JSON ─┐
AutoCAD plug-in (C#) ── DXF (DxfOut) ───────┤
Web app (React) ─────── IFC / DXF upload ───┤
                                            ▼
                    FastAPI ──▶ job: authority → overlays + planning → classify (Nano)
                       │           → derive → evaluate (rule engine) → freshness (Tavily + Nano)
                       │           → questions (Nano) → explain (Super)
                       ▼
        SSE progress · report · BCF · mesh · live pack  ──▶ back to every front end
                       │
         SQLite · rules/*.yaml · schemas/*.json
```

- **Backend:** Python 3.12, FastAPI, IfcOpenShell, ezdxf, shapely, SQLite ([backend/](backend/)).
- **Rule engine:** [engine/expr.py](backend/src/compliance/engine/expr.py) is an AST allow-list evaluator with three-valued logic (no `eval`); [engine/evaluate.py](backend/src/compliance/engine/evaluate.py) is the only place pass/fail is decided.
- **Rules:** [rules/udcpr2020/](rules/udcpr2020/), [rules/nbc2016/](rules/nbc2016/) and the Pune layer [rules/cities/pmc/](rules/cities/pmc/) (TOD, height by road width, congested areas); compiler drafts land in [rules/drafts/](rules/drafts/).
- **Web:** Vite, React, TypeScript, Tailwind, Leaflet, three.js ([web/](web/)).
- **Revit add-in:** [revit-addin/](revit-addin/). It never modifies model elements; it only writes its own Extensible Storage and the "Compliance Check" view.
- **AutoCAD plug-in:** [autocad-addin/](autocad-addin/). It exports a DXF copy of the open drawing (the drawing itself is untouched) and adds only its own tagged clouds and labels on the `COMPLIANCE ISSUES` layer.
- **Hosting:** one container ([deploy/Dockerfile](deploy/Dockerfile)): Node builds the web app, FastAPI serves the API and the static files; SQLite on a mounted volume. The public instance runs on Railway at compliance.getperspec.com.

## Run it locally

Prerequisites: [uv](https://docs.astral.sh/uv/) (Python 3.12), Node.js 22+, [just](https://github.com/casey/just). For the plug-ins: .NET 8 SDK, and Revit 2026 or AutoCAD 2026.

1. **Keys.** Copy `.env.example` to `.env` and set `NEBIUS_API_KEY` ([Token Factory](https://tokenfactory.nebius.com/)) and `TAVILY_API_KEY` ([Tavily](https://tavily.com/)). Without them the rule engine still works, but room classification, layer suggestions, the freshness check, explanations and the rule compiler are skipped or unavailable.
2. **Install and build.**
   ```sh
   just setup        # backend dependencies
   just build-web    # web app → web/dist
   ```
3. **Run.**
   ```sh
   just dev-backend  # http://127.0.0.1:8000 serves the API and the web app
   ```
   Open http://127.0.0.1:8000 and click a sample, or upload an IFC or DXF. For web development with hot reload, also run `just dev-web` and open http://localhost:5173.
4. **Revit (optional).** Close Revit, run `just install-addin`, start Revit and choose *Always Load*. In the web app, open **pair Revit · AutoCAD** for a code, then in Revit use *Compliance → Pair* (server `http://localhost:8000` for a local run), *Site Setup* and *Run Check*. `just package-addin` builds the release zip with `install.ps1`.
5. **AutoCAD (optional).** Close AutoCAD, run `just install-autocad`, start AutoCAD and open the **Compliance** ribbon tab: *1 Pair*, *2 Layers*, *3 Site*, *4 Run Check*. `just package-autocad` builds the release zip.

**Docker:** `docker compose -f deploy/docker-compose.yml up --build` serves the app on port 8000 (with Caddy for HTTPS when `DOMAIN` is set). On Railway, [railway.json](railway.json) builds the same Dockerfile; mount a volume at `/data` and set the two keys as variables.

### Tests and tools

```sh
just test-backend        # rule engine, agents (mocked), API, IFC/DXF/BCF adapters
just test-addin          # plug-in core logic: API client, live engine (no Revit needed)
just lint
just find-clause "minimum width of stair"   # search the source PDFs (after just extract-sources)
just compile-rule fixtures/clauses/udcpr-9.4.1-wc.txt   # clause text → draft rule
just make-samples        # regenerate the sample IFC and DXF files and their thumbnails
```

## Sources and data

- UDCPR 2020 (Maharashtra, consolidated Jan 2025) is the primary rulebook; NBC 2016 is the fallback. Source PDFs are not redistributed: [sources/manifest.yaml](sources/manifest.yaml) lists the documents and, where they are public, their download links.
- Metro stations, land use and map tiles: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, ODbL. Addresses via Nominatim; land use via the Overpass API.
- IFC handling uses [IfcOpenShell](https://ifcopenshell.org/) (LGPL-3.0); DXF handling uses [ezdxf](https://ezdxf.mozman.de/) (MIT).
- Revit and AutoCAD are trademarks of Autodesk, Inc. This project is not affiliated with or endorsed by Autodesk.

## Licence

[Apache License 2.0](LICENSE).
