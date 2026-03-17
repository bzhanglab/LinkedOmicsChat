# NAR Publication Plan: cpgAgent → LinkedOmics AI Assistant

---

## Context
cpgAgent is a conversational AI interface over cancer multi-omics data (TCGA + CPTAC + LinkedOmics). The goal is to make it publishable in the NAR Web Server Issue as the first AI-powered natural language interface to LinkedOmics/TCGA/CPTAC data.

## Current Build Snapshot (as of 2026-03-11)
- Core platform is live: FastAPI backend, MCP Aggregator, LangGraph orchestrator, LinkedOmics MCP all working.
- Only `linkedomics_server.py` exists in `mcp_servers/` — 7 real tools (funmap_neighborhood, get_target, cancer_gene_expression, overall_survival_per_cancer, clinical_trial_information, get_cis_correlations, webgestalt).
- Dead code removed: `tcga_service.py`, `cptac_service.py`, `data_server.py` all deleted.
- LLM hallucination on TCGA questions fixed: system prompt now has explicit NOT AVAILABLE section and dynamic data-access section from `_build_data_access_section()`.
- LLM formatting fixed: no longer dumps raw Python dicts; uses markdown tables.
- Guest mode, auth, chat history, right panel, use cases, citations, LaTeX rendering all working.

---

## Current Gaps (vs. NAR Web Server Issue Requirements)

| Gap | Severity | Status |
|-----|----------|--------|
| No real TCGA data (GDC API not integrated) | 🔴 Blocking | Not started |
| No real CPTAC protein-level data beyond LinkedOmics tools | 🔴 Blocking | LinkedOmics covers RNA+protein expression; raw CPTAC package not integrated |
| No stable public URL / production deployment | 🔴 Blocking | Docker scaffold exists, no confirmed public URL |
| `analysis_agent.py` still uses `np.random` mock data (fallback path) | 🟡 Required | Not started |
| No rate limiting enforcement (config exists but no middleware) | 🟡 Required | Not started |
| Literature agent uses DuckDuckGo only (falsely claims PubMed access) | 🟡 Required | Not started |
| VisualizationsPanel is hardcoded mock data — not wired to real sessions | 🟡 Required | Not started |
| No backend export API or viz download (frontend Markdown export exists) | 🟡 Required | In progress |
| No session sharing / reproducible links | 🟡 Required | Not started |
| OpenAPI docs missing contact/license/tags/API links | 🟢 Recommended | In progress |
| No biological validation / ground-truth test suite | 🟡 Required | Not started |
| No case studies demonstrating real biology (needed for paper) | 🟡 Required | Not started |
| No architecture diagram for paper | 🟢 Recommended | Not started |
| Tool name "cpgAgent" implies CpG methylation — misleading | 🟢 Recommended | Decision pending |
| No Nginx reverse proxy / SSL | 🔴 Blocking | Not started |

---

## Completed ✅

### Platform Foundation
- `backend/services/mcp_aggregator.py` — MCP aggregation
- `backend/services/langgraph_orchestrator.py` — LangGraph chaining / streaming with tool-grounded system prompt
  - `_build_data_access_section()` — dynamically lists enabled MCP servers; prevents hallucination
  - FORMATTING RULES — prevents raw dict output
  - NOT AVAILABLE section — LLM correctly says "I don't have TCGA/GDC data" instead of hallucinating
- `backend/mcp_servers/linkedomics_server.py` — 7 real LinkedOmics tools
- `backend/api/tools.py` + `frontend/components/ToolExplorer.tsx` — direct MCP tool browsing / execution UI
- `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile` — container stack scaffold

### Dead Code Removal ✅ (2026-03-11)
- Deleted: `backend/mcp_servers/data_server.py`
- Deleted: `backend/services/tcga_service.py`
- Deleted: `backend/services/cptac_service.py`
- Cleaned dead imports from `association_agent.py`, `differential_expression_agent.py`

### Milestone 2A: Guest/Demo Mode ✅
- `get_optional_user()` dependency, in-memory guest sessions
- "Continue as Guest" button on login page
- Guest banner on main page

### UX Improvements ✅
- Friendly progress labels during tool execution
- Data source citation pills below responses
- LaTeX math rendering
- Dark mode text color fixes
- Chat history preserved across sidebar panel switches
- Auth token validation timeout reduced (10s → 3s)

---

## What to Improve Next (Priority Order)

### 🔴 Priority 1: Nginx + SSL (Prerequisite for Public URL)
Without a public URL, NAR reviewers cannot access the tool.

**Create:** `nginx/nginx.conf`
```nginx
server {
    listen 80;
    location /api/ { proxy_pass http://backend:8000/; proxy_read_timeout 300s; }
    location / { proxy_pass http://frontend:3000/; }
}
```
**Modify:** `docker-compose.yml` — add nginx service, uncomment SSL cert volume.

---

### 🟡 Priority 2: Rate Limiting Middleware
Required before public exposure to prevent abuse.

**Create:** `backend/core/rate_limiter.py` — Redis sliding window:
- Guests: 10 req/hour per IP (`X-Forwarded-For`)
- Authenticated: 60 req/hour per `user_id`

**Modify:** `backend/main.py` — add rate limiter as FastAPI middleware after CORS.

---

### 🟡 Priority 3: PubMed Integration
The literature agent currently uses DuckDuckGo and falsely claims PubMed access. This is a credibility issue for NAR.

**Modify:** `backend/agents/literature_agent.py` — replace DuckDuckGo with NCBI E-utilities:
- `esearch.fcgi?db=pubmed&term={query}&retmax=10` → IDs
- `efetch.fcgi?db=pubmed&id={ids}&rettype=xml` → title, authors, abstract, PMID, DOI

**Modify:** `backend/core/config.py` — add `NCBI_EMAIL: str = ""` (required by NCBI ToS).

---

### 🟡 Priority 4: Real TCGA Data via GDC MCP Server
The biggest scientific gap. LinkedOmics covers CPTAC proteogenomics, but not raw TCGA mutation frequencies, RNA-seq counts, or clinical data from GDC.

**Create:** `backend/mcp_servers/gdc_server.py` — FastMCP tools:
- `get_available_tcga_projects()` — all 33 TCGA cancer types + sample counts
- `get_tcga_mutation_frequency(gene, cancer_type=None)` — somatic mutation rates via `/ssm_occurrences` with facet aggregation
- `get_tcga_clinical_data(cancer_type)` — age, stage, vital_status via `/cases`

**Modify:** `backend/core/config.py` — add `MCP_GDC_SERVER_ENABLED: bool = False`

**Modify:** `backend/services/mcp_aggregator.py` — register gdc_server in `initialize()`

**Modify:** `backend/services/langgraph_orchestrator.py` `_build_data_access_section()` — add GDC entry when `"gdc" in servers`

Note: A working GDC server was previously implemented and tested (TP53 in BRCA = 30.6%, KRAS in PAAD = 58.4%). It was deleted to avoid TCGA/CPTAC conflation confusion. Can be recreated cleanly now that the system prompt properly distinguishes TCGA vs CPTAC.

---

### 🟡 Priority 5: Fix analysis_agent.py Mock Data
`analysis_agent.py` still uses `np.random.seed(42)` fallback paths. These are reached when MCP tools fail. Should either remove them (fail loudly) or route through real tools.

**Modify:** `backend/agents/analysis_agent.py` — replace `np.random` mock fallbacks with explicit error responses: "Analysis failed: [reason]. Please try again."

---

### 🟡 Priority 6: VisualizationsPanel — Wire to Real Session Data
Currently hardcoded mock plots. The LinkedOmics tools already return base64 PNG plots in their responses; they just need to be extracted and displayed.

**Modify:** `backend/api/chat.py` or create `backend/api/export.py` — add `GET /api/v1/chat/sessions/{id}/visualizations` that extracts base64 images from stored messages.

**Modify:** `frontend/components/VisualizationsPanel.tsx` — call the real endpoint; replace mock data; add Download PNG button.

**Modify:** `frontend/lib/api.ts` — add `visualizationsAPI.getSessionVisualizations(sessionId)`.

---

### 🟡 Priority 7: Session Sharing (Reproducible Links)
Required for NAR — reviewers need to reproduce analyses.

**Modify:** `backend/models/database.py` — add `shared_token` (UUID) and `is_public` (bool) to `ChatSession`.

**Modify:** `backend/api/chat.py` — add `POST /api/v1/chat/sessions/{id}/share` → returns shareable URL.

**Create:** `frontend/app/shared/[token]/page.tsx` — read-only session viewer.

---

### 🟡 Priority 8: Biological Validation Suite
Required to demonstrate the tool produces correct biology for the paper.

**Create:** `backend/tests/` directory.

**Create:** `backend/tests/test_biological_accuracy.py`:
```python
VALIDATION_QUERIES = [
  {"query": "Is ESR1 associated with survival in BRCA?",
   "expected_tools": ["linkedomics::overall_survival_per_cancer"],
   "expected_direction": "better", "reference": "PMID:25892560"},
  {"query": "What are TP53 functional neighbors?",
   "expected_in_neighborhood": ["MDM2", "CDKN1A"]},
  {"query": "Is EGFR overexpressed in LUAD?",
   "expected_direction": "higher"},
]
```

**Create:** `backend/tests/run_case_studies.py` — runs 5 NAR case studies, outputs `case_study_results.json`.

---

### 🟢 Priority 9: OpenAPI Documentation Enhancement
**Modify:** `backend/main.py` — add `contact`, `license_info`, `tags_metadata` to `FastAPI()`.

**Modify:** `frontend/app/docs/page.tsx` — add Swagger/ReDoc links, citation BibTeX block, data-source attribution (LinkedOmics, GDC, PDC/CPTAC, WebGestalt), GitHub link.

---

### 🟢 Priority 10: Architecture Diagram + Paper Support
**Create:** `docs/generate_architecture_diagram.py` — matplotlib figure:
- Browser → Next.js → FastAPI → LangGraph → MCP Aggregator → [LinkedOmics | GDC] MCPs → APIs

**Create:** `docs/comparison_table.md`

| Feature | LinkedOmics | cBioPortal | cpgAgent |
|---------|------------|------------|---------|
| Natural language interface | No | No | **Yes** |
| Multi-step auto-chaining | No | No | **Yes (LangGraph)** |
| TCGA mutation data | Yes | Yes | **Yes (GDC API)** |
| CPTAC proteogenomics | Yes | Partial | **Yes (LinkedOmics)** |
| PubMed literature mining | No | No | **Yes** |
| Export (Markdown/TSV) | Partial | Yes | **Yes** |
| Reproducible shared links | No | Yes | **Yes** |
| REST API | No | Yes | **Yes** |
| Open source | No | Yes | **Yes** |

---

## Tool Name Decision
"cpgAgent" implies CpG methylation. Suggested alternatives:
- **LinkedOmics-AI** — leverages brand recognition (check with LinkedOmics team)
- **OmicsChat** — broad, descriptive
- **CancerOmicsAgent** — descriptive

Discuss with PI before domain registration.

---

## Verification Checklist

1. `docker compose up` → all containers healthy
2. Visit public URL without login → guest mode loads with banner
3. Ask "What TCGA cancer types are available?" → "I don't have access to TCGA/GDC data" (currently passing ✅)
4. Ask "What is the TP53 mutation rate in BRCA?" → declines gracefully (currently passing ✅)
5. Ask "Show ESR1 expression in BRCA" → calls `linkedomics::cancer_gene_expression`, returns real data
6. Ask "Find BRCA1 partners and run enrichment" → LangGraph chains `funmap_neighborhood` → `webgestalt`
7. Click Export on a session → markdown report downloads
8. Click Share → link opens read-only view without login
9. `python backend/tests/run_case_studies.py` → all 5 case studies complete
10. `python backend/tests/test_biological_accuracy.py` → ≥80% match expected biology
11. Visit `/api/docs` → full Swagger UI
