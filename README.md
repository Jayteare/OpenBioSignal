# OpenBioSignal

Local-first biomedical evidence intelligence for turning a research question into a grounded evidence brief.

## Why This Exists

Literature review workflows are often fragmented across search tools, PDFs, notes, spreadsheets, and ad hoc summaries. OpenBioSignal is an attempt to make that process more inspectable and more reproducible in a single local workspace:

- start from a research question
- retrieve relevant PubMed records
- extract structured claims from ranked passages
- evaluate claim quality
- synthesize a brief with provenance

The project is intentionally local-first and lightweight so it can be inspected, modified, and run without cloud infrastructure.

## What It Does

Current pipeline:

1. Create a research run from a biomedical question.
2. Search PubMed and store candidate papers locally.
3. Fetch abstracts and chunk them into retrieval units.
4. Rank chunks with a lexical scorer plus lightweight result/conclusion boosts.
5. Extract one structured claim per top chunk.
6. Run automated claim evaluation for quality checks.
7. Generate an evidence brief, evidence view, and markdown report.

Key characteristics:

- FastAPI + Jinja server-rendered UI
- SQLite persistence for local runs and artifacts
- Inspectable claim review and evaluation workflow
- Research-output-first workspace UI with debug views available on demand
- Z.AI-backed structured generation through the OpenAI Python SDK compatibility layer

## Screenshots

Add project screenshots under `assets/screenshots/` and update these references as needed.

- Workspace view: `assets/screenshots/run-workspace.png`
- Claim review: `assets/screenshots/claim-review.png`
- Evidence brief: `assets/screenshots/brief-section.png`

## Quickstart

Requirements:

- Python 3.11+
- a virtual environment tool such as `venv`
- a Z.AI API key for claim extraction, claim evaluation, and brief generation

Create a virtual environment.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy the environment template and fill in your local settings:

```bash
cp .env.example .env
```

Or on Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Start the app:

```bash
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Environment Variables

Important settings are documented in `.env.example`.

Common local values:

```env
APP_NAME=OpenBioSignal
APP_ENV=development
DATABASE_URL=sqlite:///./openbiosignal.db
LLM_PROVIDER=zai
ZAI_API_KEY=
ZAI_MODEL=glm-5
```

Notes:

- `ZAI_API_KEY` is required for claim extraction, claim evaluation, and brief generation.
- `OPENAI_*` placeholders remain documented for future provider flexibility, but the current app is configured for Z.AI-first local use.
- SQLite tables are created automatically on startup.

## Example Research Question

Try this as an initial end-to-end run:

> Does vitamin D supplementation reduce fracture risk in older adults?

Suggested test flow:

1. Create a run.
2. Click `Run Pipeline`.
3. Review the brief, claims, evidence cards, and evaluations on the run page.

## Current Status

This is an early research prototype, not a polished production system.

Current strengths:

- the local pipeline runs end to end
- the UI is usable for inspecting search, ranking, claims, evaluations, and briefs
- claim extraction and ranking are now more evidence-aware than the initial scaffold

Current limitations:

- retrieval is still lexical and heuristic, not embedding-based
- claim extraction is single-claim-per-chunk and still imperfect
- claim evaluations are model-based heuristics, not gold-standard benchmarks
- PubMed coverage is abstract-first; full-text workflows are not implemented
- no authentication, multi-user support, or deployment story is included

## Roadmap

Near-term priorities:

- improve retrieval quality and passage selection
- improve claim faithfulness and structured extraction consistency
- make brief synthesis more selective about weak claims
- add better local export and artifact packaging
- improve benchmark-style evaluation against curated examples

See `ROADMAP.md` for a concise project roadmap.

## Contributing

Contributions, issues, and feedback are welcome. See `CONTRIBUTING.md` for a lightweight starter guide.

## Disclaimer

OpenBioSignal is a research prototype for evidence synthesis workflows. It is not medical advice, not a diagnostic tool, and not a substitute for clinical judgment or expert literature review.
