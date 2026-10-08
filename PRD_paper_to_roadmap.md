# PRD: Paper-to-Roadmap Learning Tool

**Working name:** PaperPath (placeholder)
**Status:** Draft v0.2 (adds ancestor papers)
**Last updated:** September 26, 2026

---

## 1. Overview

PaperPath takes a single arXiv paper and produces a personalized, ordered learning roadmap of the topics a reader needs to understand it. The roadmap is delivered as an interactive web view and as a downloadable Obsidian vault, with one note per topic, prerequisite links that render as a graph, and links to real learning resources. Alongside topics, the roadmap recommends a small, ranked set of earlier papers the target paper builds on, so the reader learns both the concepts and the lineage of ideas behind the work.

The system splits work between two kinds of models. A frontier LLM handles tasks that need language: extracting topics from the paper and writing explanations. Jev, TypeSafe AI's decision-only model, handles the high volume of small typed judgments: whether one topic is a prerequisite of another, whether a topic is essential or incidental, how difficult it is, and whether a Wikipedia article matches a concept, and how important an earlier paper is to understanding the target. Deterministic code handles everything that doesn't need a model, such as graph sorting and file generation.

## 2. Problem

Researchers, students, and engineers regularly need to read papers outside their current expertise. The usual process is slow and unstructured: read until confused, search for the unfamiliar term, fall into a chain of further unfamiliar terms, and repeat. Readers often can't tell which concepts are essential to the paper's main result and which are mentioned only in passing, so they either over-study or skip foundations they needed.

Existing paper-reading assistants are reactive. They explain a passage when the reader gets stuck. None reliably answers the question a reader has before starting: what am I missing, and in what order should I learn it?

## 3. Goals and non-goals

### Goals

The MVP should turn an arXiv paper into a correct, ordered prerequisite roadmap in under two minutes for a first-time paper and near-instantly for a cached one. It should personalize the roadmap by pruning topics the reader already knows, based on a short diagnostic. It should ground every learning resource in a real, verified link. It should surface the few earlier papers that matter most, rather than every reference, and keep that set bounded by a reading-time budget. And it should export the roadmap as a clean Obsidian vault that works with no plugins, with optional enhancements for users who have Dataview.

### Non-goals (MVP)

The MVP will not teach topics itself through a tutor or quizzes beyond the initial diagnostic. It will not support papers outside arXiv, topic-to-roadmap generation (a later phase), merging multiple papers into one vault, or collaboration features. It will not reproduce paper or Wikipedia text beyond short, attributed excerpts.

## 4. Target users

The primary user is a **graduate student or early-career researcher** in physics, math, CS, or another quantitative field who has been handed a paper (by an advisor, reading group, or citation trail) slightly or significantly outside their area.

Secondary users are **industry engineers and ML practitioners** who need to implement or evaluate methods from recent papers, and **advanced undergraduates** preparing for research positions.

## 5. User stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-1 | grad student | paste an arXiv link and get a roadmap | I know what to learn before reading |
| US-2 | reader with partial background | skip topics I already know | I don't waste time on basics |
| US-3 | reader | see why each topic matters for this specific paper | I stay motivated and focused |
| US-4 | reader | see which topics are essential vs. optional | I can go fast when I need to |
| US-5 | Obsidian user | download the roadmap as a vault | I can study and take notes in my own tools |
| US-6 | reader | track which topics I've finished | I know how close I am to reading the paper |
| US-7 | reader | see the handful of earlier papers this one builds on | I understand where the method came from |
| US-8 | power user | expand any earlier paper to see its own key predecessors | I can go deeper on demand without an overwhelming default view |

## 6. User flow

The user pastes an arXiv URL or ID. The system checks the cache for an existing roadmap for that paper and version; if none exists, it runs the generation pipeline while showing progress. The user then takes a short diagnostic of 5 to 10 quick questions on the highest-impact topics, or skips it. The system prunes known topics and displays the roadmap as an interactive graph and an ordered list, with recommended earlier papers placed at the point in the path where they are most useful. The user can open any topic for its explanation and resources, mark topics complete, and export the result as an Obsidian vault.

## 7. Functional requirements

### 7.1 Paper ingestion

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-1 | Accept arXiv URLs (abs, pdf, html) and bare IDs, with or without version | P0 |
| FR-2 | Fetch metadata via the arXiv API using export.arxiv.org, respecting arXiv's rate limits | P0 |
| FR-3 | Download and unpack the LaTeX source when available | P0 |
| FR-4 | Fall back to arXiv's HTML version, then PDF text extraction, when source is unavailable or unparseable | P1 |
| FR-5 | Resolve bibliography entries to canonical papers via Semantic Scholar or OpenAlex | P0 |

### 7.2 Topic extraction (frontier model)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-6 | Extract 15 to 50 candidate topics from the paper, including implicit background knowledge | P0 |
| FR-7 | For each topic, return structured JSON: name, aliases, one-line description of its use in the paper, locations (sections or equations), related references | P0 |
| FR-8 | Extract the paper's notation and map symbols to topics where possible | P1 |

### 7.3 Judgments (Jev)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-9 | Classify each topic as essential, supporting, or incidental to the paper's main contribution | P0 |
| FR-10 | Score each topic's difficulty on a fixed scale (e.g., 1 to 5) | P0 |
| FR-11 | For candidate topic pairs, decide whether A must be understood before B, with confidence | P0 |
| FR-12 | Verify that each resolved Wikipedia article matches the concept as used in the paper | P0 |
| FR-13 | Score diagnostic answers to decide which topics the user already knows | P1 |

### 7.4 Graph construction (code)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-14 | Keep prerequisite edges above a configurable confidence threshold | P0 |
| FR-15 | Detect cycles and break them by removing the lowest-confidence edge | P0 |
| FR-16 | Produce a learning order via topological sort, breaking ties by difficulty then essentiality | P0 |
| FR-17 | Apply a recursion stopping rule: do not expand prerequisites below a difficulty floor or beyond a configurable depth | P0 |

### 7.5 Resource mapping and explanations

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-18 | Resolve each topic to Wikipedia via search API; never accept model-generated URLs without verification | P0 |
| FR-19 | Link directly relevant earlier papers from the reference list where they introduce a topic | P0 |
| FR-20 | Generate a short "why this matters for this paper" explanation per topic (frontier model) | P0 |
| FR-21 | Suggest surveys, lecture notes, or open textbooks for topics where Wikipedia is insufficient | P2 |

### 7.6 Output

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-22 | Web view: interactive prerequisite graph plus ordered list, with per-topic detail panels | P0 |
| FR-23 | Progress tracking per topic (not started, in progress, done) | P1 |
| FR-24 | Obsidian export as a zipped vault (see Section 9) | P0 |

### 7.7 Ancestor papers

Earlier papers are a separate node type from topics. Topics answer "what do I need to know"; papers answer "where was this developed." Because each paper cites 30 to 60 others, naive expansion grows exponentially, so ancestor papers are selected by best-first expansion under a budget rather than exhaustive traversal.

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-25 | Build a candidate set from the target paper's resolved references, including Semantic Scholar's "influential citation" flag and citation context (section and frequency) | P0 |
| FR-26 | Score each candidate with Jev: builds directly on its method (yes/no), introduced a roadmap topic (yes/no per topic), role (choice), learner usefulness (score) | P0 |
| FR-27 | Combine scores into a priority in code, weighting method-section citations above related-work citations and boosting surveys and tutorials | P0 |
| FR-28 | Expand best-first from a priority queue until a budget is reached: default 5 to 10 papers and a configurable total reading-time estimate | P0 |
| FR-29 | Deduplicate by canonical paper ID so shared ancestors merge into one node; treat convergence (reached from multiple paths) as an importance signal | P0 |
| FR-30 | Link each paper to the topics it introduced or develops, and place it in the learning order after those topics' prerequisites | P0 |
| FR-31 | Lazy expansion: user can expand any paper node to fetch and rank its own top predecessors on demand | P1 |
| FR-32 | Estimate reading time per paper (from length and difficulty) to drive budgets and stopping | P1 |
| FR-33 | Cap expansion depth (default 2 levels from the target) regardless of budget | P0 |

## 8. System design

### 8.1 Pipeline

```
arXiv ID
  → Ingestion (HTTP: arXiv API + LaTeX source; S2/OpenAlex for references)
  → Topic extraction (frontier model, structured JSON)
  → Pruning + scoring (Jev: essentiality, difficulty)
  → Edge proposal (frontier model proposes candidate prerequisite pairs)
  → Edge verification (Jev: pairwise prerequisite judgments)
  → Graph build + topological sort (code)
  → Ancestor papers (reference candidates → Jev scoring → best-first expansion under budget, deduplicated)
  → Resource resolution (Wikipedia API + Jev match verification)
  → Explanations (frontier model)
  → Cache (keyed by arXiv ID + version)
  → Personalization (diagnostic scored by Jev; prune per user)
  → Output (web view, Obsidian vault)
```

The cached artifact is the full, unpersonalized roadmap. Personalization only removes topics, so it runs cheaply per user on top of the cached result. Paper metadata, reference lists, and Jev scores for ancestor papers are cached globally by paper ID, so lazy expansions of popular papers are shared across all users and roadmaps.

### 8.2 Tech stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | Python | Strong libraries for arXiv, LaTeX parsing, model APIs |
| Fetching | Plain HTTP (httpx or curl) | No browser needed for arXiv |
| LaTeX parsing | pylatexenc or similar | Extract sections, environments, bibliography |
| PDF fallback | GROBID or Marker | Only when source is unavailable |
| References | Semantic Scholar API, OpenAlex | Canonical IDs and citation data |
| Language tasks | Frontier LLM via API | Extraction, edge proposals, explanations |
| Judgments | Jev via TypeSafe API | Early access; also on OpenRouter and Vercel AI Gateway |
| Storage | SQLite (MVP), Postgres later | Cache, user progress, logs |
| Backend | FastAPI | Async pipeline, progress streaming |
| Frontend | React + React Flow or Cytoscape.js | Graph rendering |
| Export | Python zipfile + templated Markdown | Obsidian vault generation |

### 8.3 Jev question schema (draft)

All Jev calls share a stable prefix (fixed instructions and question definitions) followed by variable state (paper context and topic details), to maximize prompt-cache reuse.

| Question | Type | Input state | Output |
|----------|------|-------------|--------|
| Essentiality | choice | paper abstract, topic + usage description | essential / supporting / incidental |
| Difficulty | score | topic + description | 1 to 5 |
| Prerequisite | yes/no | topic A, topic B, both descriptions | yes/no + confidence |
| Wikipedia match | yes/no | topic + usage, article title + lead summary | yes/no + confidence |
| User knows topic | yes/no | topic, diagnostic question, user answer | yes/no + confidence |
| Builds on method | yes/no | target abstract + citation contexts, candidate title + abstract | yes/no + confidence |
| Introduced topic | yes/no | topic + usage, candidate title + abstract | yes/no + confidence |
| Paper role | choice | candidate title + abstract, citation contexts | foundational method / survey or tutorial / benchmark or dataset / background |
| Learner usefulness | score | candidate title + abstract, reader's roadmap topics | 1 to 5 |

### 8.4 Data model (core entities)

**Paper**: arxiv_id, version, title, abstract, source_type (latex / html / pdf), fetched_at.
**Topic**: id, paper_id, name, aliases, usage_description, locations, essentiality, difficulty.
**Edge**: from_topic, to_topic, confidence, source (proposed / verified), kept (bool).
**AncestorPaper**: canonical_id (S2/OpenAlex), arxiv_id (optional), title, year, role, reading_time_estimate, priority, depth, expanded (bool).
**PaperLink**: from_paper, to_paper, citation_contexts, influential (bool), builds_on_confidence.
**PaperTopic**: paper_id, topic_id, relation (introduced / develops), confidence.
**Resource**: topic_id, type (wikipedia / paper / other), url, verified (bool), match_confidence.
**UserRoadmap**: user_id, paper_id, pruned_topics, progress per topic.
**CallLog**: model, prompt hash, inputs, outputs, latency, cost, timestamp.

## 9. Obsidian export

The export is a zipped folder that opens directly as an Obsidian vault with no plugins required.

Each topic becomes one Markdown note named after the topic, with filenames sanitized to remove characters that break paths (such as `/`, `:`, `?`). Every note begins with YAML frontmatter containing topic, aliases, difficulty, essentiality, prerequisites, status, and the source paper ID. Prerequisites appear as `[[wikilinks]]` in the note body so Obsidian's graph view renders the prerequisite graph automatically. Math uses Obsidian's native LaTeX syntax.

An index note, `00 Roadmap - <paper title>.md`, lists the full learning order with links, marks essential topics, and includes an optional Dataview query for progress tracking that degrades gracefully if the plugin isn't installed. Each recommended earlier paper becomes its own note in a `Papers/` folder, with frontmatter including `type: paper`, the arXiv or canonical ID, year, role, estimated reading time, and status. The note contains a short explanation of why this paper matters for the target, wikilinks to the topics it introduced, and a link to the paper itself. The index note places papers inline in the learning order, marked as readings. Topic notes link back to the papers that introduced them, so Obsidian's graph view shows both the concept structure and the lineage of ideas.

A `.canvas` file (JSON Canvas format) lays out the roadmap visually, with topics positioned by their level in the topological sort, paper cards visually distinct from topic cards, and arrows for prerequisites and paper lineage.

Before export, a validation step confirms every wikilink resolves to an existing note and every frontmatter block parses.

Notes contain original explanations and links rather than copied text. Any short Wikipedia excerpt must carry attribution per CC BY-SA.

## 10. Success metrics

### Primary

**Comprehension speed:** time for a user to correctly answer a set of comprehension questions about the target paper, compared with control groups using a general chatbot or unassisted search. Target: at least 30% faster than the chatbot baseline in pilot studies.

### Quality metrics

| Metric | Method | MVP target |
|--------|--------|------------|
| Prerequisite edge precision | Expert review of sampled edges | ≥ 85% |
| Essential topic recall | Compare against expert-written prerequisite lists for benchmark papers | ≥ 90% |
| Ancestor paper precision | Expert rating of whether each recommended paper is worth reading for the target | ≥ 80% |
| Key ancestor recall | Compare against expert-chosen "must-read predecessors" for benchmark papers | ≥ 80% of expert picks in top 10 |
| Link validity | Automated check that every resource resolves and matches | ≥ 98% |
| Vault validity | Automated check of links and frontmatter | 100% |

### Operational metrics

Generation time under two minutes for uncached papers at p90; cached roadmaps served in under two seconds; and per-paper generation cost tracked separately for Jev and frontier model calls.

## 11. Evaluation plan

Build a benchmark of 10 to 20 well-known papers in one field the team knows well. For each, have one or two domain experts write a prerequisite list and ordering, plus a short list of must-read predecessor papers. Compare generated roadmaps against these references on edge precision and essential-topic recall. Separately, compare Jev's judgments against a frontier model acting as judge on the same inputs, to confirm Jev is at least as accurate on this task at its lower cost and latency. Call logs from every run feed a growing regression set that is re-run whenever prompts, thresholds, or models change.

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Incorrect prerequisite edges | Roadmaps send users in circles or skip foundations | Confidence thresholds, expert benchmark, user "this is wrong" feedback on edges |
| Jev underperforms on nuanced scholarly judgments | Poor graph quality | Benchmark early against frontier judge; keep model per question swappable |
| Jev availability (early access, new vendor) | Pipeline blocked | Abstract the judgment layer; frontier-model fallback for each question type |
| Implicit background not extracted | Critical gaps in roadmap | Explicit extraction prompt for assumed knowledge; diagnostic surfaces gaps |
| Wikipedia inadequate for advanced topics | Dead ends in roadmap | Link foundational papers from references; add surveys and lecture notes (P2) |
| Recursion explosion | Huge, unusable roadmaps | Depth cap, difficulty floor, essential-only default view |
| arXiv rate limits or source parsing failures | Slow or failed generation | Respect limits, cache aggressively, HTML and PDF fallbacks |
| Ancestor expansion grows exponentially | Unusable roadmaps, high cost, slow generation | Best-first expansion, paper budget, reading-time budget, depth cap, lazy expansion |
| Recommended papers too hard or too long for the reader | Users stall | Learner-usefulness score, reading-time estimates, boost surveys and tutorials |
| Incomplete citation metadata | Missed key predecessors | Combine Semantic Scholar and OpenAlex; fall back to parsed bibliography |
| Licensing issues with copied content | Legal exposure | Link and summarize; attribute any excerpts |

## 13. Milestones

| Phase | Scope | Exit criteria |
|-------|-------|---------------|
| M0: Prototype | CLI: arXiv ID in, ordered topic list out; one field | Runs end to end on 10 benchmark papers |
| M1: Quality | Jev judgments, graph build, resource verification, call logging | Meets edge precision and recall targets on benchmark |
| M1.5: Ancestor papers | Candidate scoring, best-first expansion, deduplication, topic linking | Meets ancestor precision and recall targets on benchmark |
| M2: Export | Obsidian vault and canvas generation with validation, including paper notes | Vaults open cleanly with zero broken links |
| M3: Web MVP | Web view, diagnostic, personalization, caching, lazy paper expansion | Pilot with 10 to 20 users |
| M4: Pilot study | Comprehension-speed study vs. baselines | Primary metric target met or clear learnings |

## 14. Future directions

Once enough papers are processed in a field, the per-paper graphs can be merged into a field-level prerequisite graph, which enables the topic-to-roadmap product (beginner to research frontier) with little additional work. The ancestor-paper graph also accumulates into a field-level lineage map, showing how key methods developed over time. Other later features include merging new papers into an existing Obsidian vault, a daily screen of new arXiv submissions against a user's interests, support for journals via OpenAlex, and lightweight quizzes per topic.

## 15. Open questions

1. Which field should the MVP benchmark target first?
2. Does Jev support prompt caching, and if so, automatically or through explicit breakpoints? This affects the prefix design in Section 8.3.
3. Should the diagnostic be multiple choice (easier to score) or free text (more informative)?
4. Is the product free, paid, or a personal tool first? This determines how much the web MVP matters relative to a CLI plus Obsidian export.
5. How should user feedback on wrong edges flow back into the cached roadmap for all users?
6. What default paper budget and reading-time budget feel right to users? This should be tuned in the pilot.
7. Should ancestor papers from outside arXiv (journals, conference proceedings without preprints) be recommended in the MVP when they can be linked but not parsed?
