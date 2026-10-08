# PaperPath

Turn one arXiv paper into an ordered prerequisite roadmap and an Obsidian vault.

Give PaperPath an arXiv link and it works out which topics you need to understand the paper, orders them so prerequisites come first, recommends a small set of earlier papers the work builds on, and links each topic to a verified learning resource. The result is available from the command line, over an HTTP API, and as a downloadable Obsidian vault.

The full product spec lives in [PRD_paper_to_roadmap.md](PRD_paper_to_roadmap.md).

## How it works

Work is split between two kinds of models and plain code:

- **A frontier chat model** (via OpenRouter, default `openai/gpt-4.1`) handles language: extracting topics, proposing prerequisite edges, and writing explanations.
- **Jev** (`typesafe/jev-1.13` via the OpenRouter Decisions API) handles the many small typed judgments: essential vs. incidental, difficulty, whether A must come before B, whether a Wikipedia article matches a topic, and how important an earlier paper is. If Jev is unavailable, judgments fall back to the frontier model (`PAPERPATH_JEV_FALLBACK=frontier`).
- **Deterministic code** handles graph building, ordering, personalization, and vault generation.

The pipeline runs these stages in order (`src/paperpath/pipeline/wiring.py`):

1. **Ingestion** — fetch arXiv metadata and LaTeX source, resolve references via Semantic Scholar / OpenAlex
2. **Topic extraction** — frontier model
3. **Judgments** — essentiality and difficulty (Jev)
4. **Edge proposal** — candidate prerequisite pairs (frontier model)
5. **Edge verification** — keep or drop each edge (Jev)
6. **Graph** — build the DAG and order it
7. **Ancestors** — rank earlier papers within a reading-time budget
8. **Resources** — match topics to Wikipedia articles
9. **Explanations** — why each topic matters for this paper

Roadmaps are cached in SQLite per paper version, so a second request for the same paper returns immediately.

## Requirements

- Python 3.12+
- An [OpenRouter](https://openrouter.ai) API key (covers both the frontier model and Jev)
- Optional: a Semantic Scholar API key for higher rate limits

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# then set PAPERPATH_OPENROUTER_API_KEY and PAPERPATH_CONTACT_EMAIL
```

## Usage

### Command line

Print the ordered learning path for a paper:

```bash
python -m paperpath https://arxiv.org/abs/1706.03762
```

Export an Obsidian vault as a zip:

```bash
python -m paperpath https://arxiv.org/pdf/1706.03762.pdf -o roadmap.zip
```

Accepted inputs: arXiv `abs`, `pdf`, and `html` URLs, or a bare ID, with or without a version. Pass `--database-url` to use a different database.

### HTTP API

```bash
python -m paperpath serve --host 127.0.0.1 --port 8000
```

Interactive docs are at `http://127.0.0.1:8000/docs`. All routes are under `/v1`:

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/roadmaps` | Start (or reuse) a roadmap. Body: `{"arxiv": "1706.03762"}` |
| `GET` | `/roadmaps/{id}` | Job status, and the roadmap once ready. `?user_id=` personalizes; `?audit=true` includes dropped edges |
| `GET` | `/roadmaps/{id}/events` | Server-sent progress events per pipeline stage |
| `GET` | `/roadmaps/{id}/diagnostic` | Short quiz on the highest-impact topics |
| `POST` | `/roadmaps/{id}/personalize` | Prune topics the reader already knows (from IDs or diagnostic answers) |
| `POST` | `/roadmaps/{id}/progress` | Mark a topic or paper `not_started`, `in_progress`, or `done` |
| `POST` | `/roadmaps/{id}/expand?canonical_id=` | Expand an ancestor paper into its own key predecessors |
| `GET` | `/roadmaps/{id}/export` | Download the Obsidian vault zip (`?user_id=` for a personalized one) |
| `GET` | `/roadmaps/{id}/costs` | Model spend for the roadmap, by model |
| `GET` | `/health` | Liveness check (not under `/v1`) |

Generation runs in the background by default; poll `GET /roadmaps/{id}` or subscribe to `/events`. Set `PAPERPATH_INLINE_JOBS=true` to run it inside the request instead.

### Obsidian vault

The exported vault works without plugins and contains:

- `00 Roadmap - <paper title>.md` — index note with the ordered path
- one note per topic, with YAML frontmatter (difficulty, essentiality, prerequisites, status) and `[[wikilinks]]` to its prerequisites so Obsidian's graph view shows the structure
- `Papers/` — one note per recommended earlier paper
- `Roadmap.canvas` — the prerequisite graph as an Obsidian canvas

## Configuration

Settings are read from the environment or `.env`, all with the `PAPERPATH_` prefix (`src/paperpath/config.py`). The most common:

| Variable | Default | Notes |
|----------|---------|-------|
| `OPENROUTER_API_KEY` | — | Required for generation |
| `CONTACT_EMAIL` | — | Sent in the User-Agent; arXiv asks clients to identify themselves |
| `DATABASE_URL` | `sqlite:///./data/paperpath.db` | |
| `DATA_DIR` | `./data` | Downloaded sources and the database |
| `FRONTIER_MODEL` | `openai/gpt-4.1` | Any OpenRouter chat model |
| `JEV_MODEL` | `typesafe/jev-1.13` | |
| `JEV_FALLBACK` | `frontier` | `frontier` or `none` |
| `S2_API_KEY` | — | Semantic Scholar |
| `OPENALEX_MAILTO` | — | Falls back to `CONTACT_EMAIL` |
| `CONFIDENCE_THRESHOLD` | `0.7` | Minimum confidence to keep a prerequisite edge |
| `ANCESTOR_PAPER_BUDGET` | `8` | Max recommended earlier papers |
| `ANCESTOR_READING_MINUTES` | `240` | Reading-time budget for earlier papers |
| `DIAGNOSTIC_QUESTIONS` | `8` | Questions in the diagnostic |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | For a local frontend |

## Project layout

```
src/paperpath/
  cli.py          command-line entry point
  app.py          FastAPI app and error mapping
  api/            routes and request/response schemas
  clients/        arXiv, Semantic Scholar, OpenAlex, Wikipedia, frontier, Jev
  pipeline/       runner, job hub, prompts, and the stages listed above
  domain/         models, graph, ordering, personalization, arXiv ID parsing
  judgments/      Jev question catalog and response parsing
  db/             SQLAlchemy models and the Store repository
  export/         Obsidian vault builder and validator
tests/            pytest suite with fake clients (no network)
```

## Development

```bash
pytest          # runs offline against fakes in tests/fakes.py
ruff check .
ruff format .
```

## Limitations

- arXiv papers only.
- PDF text extraction is not wired in yet; papers without LaTeX source or arXiv HTML will fail ingestion. `UnavailablePdfExtractor` in `clients/jev.py` is the slot for GROBID or Marker.
