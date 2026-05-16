# ReportForge — Comprehension Debt Skeleton

Use this as a **map of what you must learn** to work safely in the repo: where behavior lives, what is wired vs. aspirational, and which names/docs mislead. Fill in notes as you read code.

> **Comprehension debt** = the gap between “what the README/architecture diagram says” and “what `JobManager.run_job` actually does today.”

---

## 0. One-screen mental model

```
[ Streamlit ] --HTTP--> [ FastAPI routers ] --> [ JobManager (in-memory job state) ]
                              |                         |
                              |                         +--> Agents (planner, research, writer, verifier)
                              |                         +--> tools/* (fetch, export, LLM, citation)
                              v
                         [ SQLite: jobs, traces, quotas ]
                         [ storage/: reports, checkpoints ]
```

**Primary execution path:** `POST /jobs` → `JobManager.run_job`  
**Secondary / demo path:** `orchestration/workflow.py` → `ReportWorkflow.run` (not used by HTTP)

---

## 1. Repository layers (what to read first)

| Layer | Path | You need to understand… | Debt hotspot |
|-------|------|-------------------------|--------------|
| HTTP surface | `app/main.py`, `app/routers/*` | Route → `JobManager` / export tools | Export bypasses `FormatterAgent` |
| Orchestration | `orchestration/job_manager.py` | **Real** pipeline | In-memory sections; DB is partial |
| Alternate orchestration | `orchestration/workflow.py` | Demo workflow + critic | Easy to confuse with production |
| Agents | `agents/*.py` | Capability per agent | 4 of 8 agents not in `run_job` |
| Tools | `tools/**` | Side-effecting I/O, no “agent logic” | RAG/search mostly unused in MVP |
| Contracts | `schemas/*.py` | Pydantic truth for API + agents | `WriterInput.rolling_summary` overload |
| UI | `frontend/streamlit_app.py` | Polls API only | File upload not wired |
| Config | `app/config.py`, `.env.example` | Provider + quotas | Kimi blocked at `$0` guard |
| Persistence | `app/database.py`, `storage/` | What survives restart | Job sections lost if only DB read |
| Specs / plan | `specs/`, `README.md` | Intended product | vs. MVP implementation |

---

## 2. Agent capability matrix

Legend: **Wired** = called from `JobManager.run_job` · **Partial** = exists but different entry · **Latent** = implemented, not in HTTP path

| Agent | File | Wired? | Uses LLM? | Primary inputs | Primary outputs | Tools / deps accessed |
|-------|------|--------|-----------|----------------|-----------------|------------------------|
| **Planner** | `agents/planner_agent.py` | Yes | Yes (`CostTrackingModel` → `ModelRouter`) | `ReportJob` (topic, type, depth) | `PlannerOutput` (outline, questions, word target) | `tools/llm/*`, `orchestration/cost_tracking` |
| **Research** | `agents/research_agent.py` | Yes | No | `job_id`, `topic`, `urls[]` | `ResearchOutput` → `Source[]` | `tools/search/url_fetcher` · optional mock via `allow_mock_sources` |
| **Report writer** | `agents/writer_agent.py` | Yes | Yes | `WriterInput` (section, evidence[], rolling_summary) | `WriterOutput` (content, claims, sources_used) | `tools/llm/*` · **not** `tools/rag/*` in MVP path |
| **Verifier** | `agents/verifier_agent.py` | Yes | Optional (`use_llm`; **off** in `run_job`) | `ReportSection`, `Source[]` | `VerifierOutput` (claims, blockers, warnings) | `tools/citation_checker` · `tools/llm/*` if enabled |
| **Critic** | `agents/critic_agent.py` | Partial (`workflow.py` only) | Yes | Markdown (+ optional sources/verifier) | `CriticOutput` (score, fixes) | `tools/llm/*` |
| **Document reader** | `agents/document_reader_agent.py` | Latent | No | File paths | `DocumentReaderOutput` | `tools/pdf_reader`, `docx_reader`, `csv_reader` |
| **Data analyst** | `agents/data_analyst_agent.py` | Latent | No | CSV/XLSX path, output dir | charts, insights dict | `pandas`, `tools/charts/generation` |
| **Formatter** | `agents/formatter_agent.py` | Latent | No | job_id, markdown, formats | `FormatterOutput` (paths) | `tools/export/pdf`, `docx` · API uses export tools **directly** |

### Agent I/O schemas (quick ref)

| Agent | Output schema (`schemas/agent_outputs.py`) |
|-------|---------------------------------------------|
| Planner | `PlannerOutput` |
| Research | `ResearchOutput` |
| Writer | `WriterOutput` |
| Verifier | `VerifierOutput` |
| Critic | `CriticOutput` |
| Document reader | `DocumentReaderOutput` |
| Formatter | `FormatterOutput` |

**Debt:** README agent catalog lists 8 agents in one pipeline; HTTP MVP uses **4** (+ export tools, not Formatter agent).

---

## 3. Tool inventory & consumers

### 3.1 LLM stack (`tools/llm/`)

| Tool / module | Responsibility | Used by |
|---------------|----------------|---------|
| `model_router.py` | Gemini / Groq / Ollama / Kimi routing; `RoutedModel.__call__` | All LLM agents via `CostTrackingModel` |
| `quota_manager.py` | Daily Gemini requests, Groq tokens (SQLite) | `CostTrackingModel` on every LLM call |
| `cost_estimator.py` | Token cost + Kimi estimate | `CostTrackingModel` |

### 3.2 Search & evidence (`tools/search/`, readers)

| Tool | Responsibility | Used by |
|------|----------------|---------|
| `url_fetcher.py` | HTTP fetch + text extract | **ResearchAgent** (production) |
| `mock_search.py` | Fake search hits | Tests; Tavily fallback |
| `tavily_search.py` | Tavily API (currently falls back to mock) | **Not** wired in ResearchAgent MVP |
| `pdf_reader.py`, `docx_reader.py`, `csv_reader.py` | Upload parsing | **DocumentReaderAgent** (latent) |

### 3.3 RAG (`tools/rag/`) — **latent in HTTP path**

| Tool | Responsibility | Used by |
|------|----------------|---------|
| `chunking.py`, `embeddings.py` | Chunk + embed | Tests / future writer |
| `vector_store.py`, `bm25_store.py` | Indexes | `hybrid_retriever.py` |
| `hybrid_retriever.py`, `reranker.py` | Retrieve evidence | Tests only today |

**Debt:** README diagram shows Writer → RAG; `JobManager` passes **flat evidence strings** from research URLs, not hybrid retrieval.

### 3.4 Quality & export

| Tool | Responsibility | Used by |
|------|----------------|---------|
| `citation_checker.py` | Map claim status → export blockers | **VerifierAgent** |
| `export/markdown.py` | Assemble MD | `JobManager.export_markdown` |
| `export/pdf.py`, `export/docx.py` | Binary exports | `app/routers/export.py` (+ FormatterAgent) |
| `charts/generation.py` | Plot files | **DataAnalystAgent** (latent) |
| `storage.py` | Ensure storage dirs | App lifespan |
| `cleanup/retention.py` | Retention policy | Ops / scripts (verify call sites) |

---

## 4. Production pipeline (fill in as you trace)

**Entry:** `app/routers/jobs.py:create_job` → `manager.create_job` → `background_tasks` → `manager.execute` → `run_job`

```
[1] PlannerAgent.run(job)
         |
         v
[2] ResearchAgent.research(job_id, topic, urls)     <-- urls from API only; no upload path
         |
         v
[3] FOR each section in planner.outline:
         ReportWriterAgent.write(WriterInput)
         VerifierAgent.run(section, sources)         <-- use_llm=False in job_manager
         |
         v
[4] _final_status  +  HITL?  +  blockers?
         |
         v
[5] Client: GET export/*  (blocked if claim.blocks_export)
```

| Step | Progress % (approx) | Active agent label | State stored in |
|------|---------------------|--------------------|-----------------|
| Plan | ~10 | PlannerAgent | memory + trace row |
| Research | ~30 | ResearchAgent | `sources_by_job` |
| Write/verify loop | 40–90 | ReportWriterAgent / VerifierAgent | `job.sections` |
| Done | 100 | — | status + optional `awaiting_approval` |

**Checkpoint / retry debt:** `orchestration/checkpoints.py` + `ReportWorkflow` save step state; `JobManager.retry` **re-runs full** `run_job`, not fine-grained resume.

---

## 5. Alternate pipeline (comprehension trap)

`orchestration/workflow.py` — **do not assume this runs in Docker/API**

```
Planner -> Research -> Writer (first section only) -> Verifier -> Critic
         \________ CheckpointStore per step ________/
```

| Question | Answer (verify in code) |
|----------|-------------------------|
| Who calls this? | Tests / manual use; not `JobManager` |
| Research input | Topic only (no URL list in signature) |
| Critic included? | Yes |
| Sections written | One |

---

## 6. Data model & naming debt

### 6.1 Core entities

| Concept | Schema | Lives in production as… |
|---------|--------|-------------------------|
| Job | `ReportJob` | `JobManager.jobs[id]` (+ `report_jobs` row) |
| Section | `ReportSection` | In-memory on job |
| Source | `Source` | `sources_by_job[id]` |
| Claim | `Claim` | Nested under section; `citation_key` vs `source_ids` |
| Trace | `AgentTrace` | Memory + `agent_traces` table |

### 6.2 Overloaded / confusing fields

| Field | Intended use | Actual / bridge behavior |
|-------|--------------|---------------------------|
| `WriterInput.rolling_summary` | Prior sections summary | Also carries **JSON section_plan** from planner |
| `Claim.source_ids` | DB source UUIDs | Often **citation keys** until verifier maps them |
| `Source.citation_key` | Bracket form `[Key]` | Writer regex expects same in prose |
| `ReportSection.sources` | Source IDs | Populated with all research sources per section |

### 6.3 Status enums to memorize

| Enum | Values that matter for UI |
|------|---------------------------|
| `ReportStatus` | `pending`, `running`, `awaiting_approval`, `completed`, `failed` |
| `VerificationStatus` | `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, `UNVERIFIED` |

**HITL rule** (`orchestration/hitl.py`): `investment_memo`, `policy_brief`, or `depth=deep` → `awaiting_approval`.

---

## 7. External systems map

| System | Config | Called from | Failure mode |
|--------|--------|-------------|--------------|
| Gemini API | `GEMINI_API_KEY`, `GEMINI_MODEL_NAME` | `RoutedModel._call_gemini` | 429 quota; stub if no key |
| Groq API | `GROQ_API_KEY` | `_call_groq` | 429 quota |
| Ollama | `OLLAMA_BASE_URL` | `_call_ollama` | Local timeout; verifier disables LLM |
| Kimi | `KIMI_API_KEY`, `MAX_COST_USD_PER_JOB` | Router | **Blocked** at `$0` guard |
| Tavily | (in tavily module) | Not in ResearchAgent path | Falls back to mock |
| SQLite | `DATABASE_URL` | Jobs, traces, quotas | Sections not fully rehydrated |
| User URLs | `CreateJobRequest.urls` | ResearchAgent | Empty URLs → empty evidence |

---

## 8. UI vs backend debt

| UI feature (`streamlit_app.py`) | Backend support today |
|--------------------------------|------------------------|
| Topic + type + depth + provider | Yes → `POST /jobs` |
| URL textarea | Yes → `urls` |
| File uploader (PDF/DOCX/CSV) | **No API call** — comprehension trap |
| Progress poll | Yes → `/jobs/{id}/progress` |
| Approve (HITL) | Yes → `/approve` |
| Regenerate section | Yes — **append feedback**, no full agent rerun |
| Export MD/PDF/DOCX | Yes — gated by verifier blockers |
| Quota sidebar | Yes → `/costs/quota` |

---

## 9. README / diagram vs code (explicit debt register)

| Document says | Code does (MVP) | Impact |
|---------------|-----------------|--------|
| Writer uses RAG pipeline | Flat URL evidence strings | Don’t debug RAG when writer mis-cites |
| Research uses Tavily | URL fetch only | Need URLs at job create |
| 8-agent linear workflow | 4 agents in `run_job` | Unused agents are not dead code—tests/specs |
| Checkpoint recovery | Full job retry | No step-level resume in JobManager |
| Document reader in architecture | Not in HTTP path | Uploads misleading in UI |
| Formatter agent in catalog | Router calls `write_pdf`/`write_docx` | Two export code paths |
| Critic in architecture | Only in `workflow.py` | Quality pass not in production job |

---

## 10. Onboarding checklist (reduce debt deliberately)

- [ ] Run `POST /jobs` with **2+ URLs** and trace one section in logs
- [ ] Read `JobManager.run_job` end-to-end (ignore `workflow.py` until later)
- [ ] Open `PlannerAgent.last_manifest` vs returned `PlannerOutput`
- [ ] Follow one `Source` from fetch → writer evidence → claim → verifier → export blocker
- [ ] Hit `awaiting_approval` with `investment_memo` + `approve`
- [ ] Trigger export block: unsupported claim → 409 on export
- [ ] Read `CostTrackingModel` + `/costs/quota` after a few LLM calls
- [ ] Skim **latent** agents (`document_reader`, `data_analyst`, `formatter`, `critic`) so you don’t “wire them twice”
- [ ] Run `uv run pytest` and note which tests encode **spec** vs **MVP**

---

## 11. Open questions (maintain as you learn)

| # | Question | Where to look |
|---|----------|---------------|
| 1 | Should research call Tavily when `urls` empty? | `research_agent.py`, `tavily_search.py` |
| 2 | When will RAG replace flat evidence? | `writer_agent.py`, `tools/rag/` |
| 3 | How should uploads reach `DocumentReaderAgent`? | New API + Streamlit wiring |
| 4 | Single export path: FormatterAgent vs router? | `export.py`, `formatter_agent.py` |
| 5 | Rehydrate `ReportJob.sections` from DB on restart? | `database.py`, `job_manager.py` |
| 6 | Enable verifier LLM in production? | `job_manager.py` line `use_llm=False` |

---

## 12. Related docs

| Doc | Purpose |
|-----|---------|
| `README.md` | Quickstart, API curl examples, env table |
| `docs/HOW_IT_WORKS.md` | Narrative architecture (production-focused) |
| `specs/001-report-generation-platform/plan.md` | SpecKit / intended platform (AGENTS.md pointer) |
| `AGENTS.md` | Pointer to spec plan |

---

## 13. Blank workspace (your notes)

### 13.1 “I thought X but actually Y”

- 
- 

### 13.2 Files I still don’t understand

- 
- 

### 13.3 Safe extension points (if building features)

- New evidence source → extend **ResearchAgent** + `Source` schema
- New report type / HITL rule → `schemas/reports.py` + `hitl.py`
- New export format → `tools/export/` + `app/routers/export.py`
- New agent in pipeline → **only** `job_manager.run_job` unless intentionally using `workflow.py`
