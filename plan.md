# NAR Publication Plan: LinkedOmicsChat

## Scope Of This Update
This plan reflects the current repository state on 2026-03-23. It is intentionally grounded in code and config present in this repo, not unverified assumptions about external deployment.

## Context
LinkedOmicsChat is a conversational AI interface for cancer multi-omics research built around LinkedOmics, CPTAC, PubMed, FunMap, and WebGestalt workflows. The publication goal remains the NAR Web Server Issue, with emphasis on natural-language querying, reproducible sharing, and multi-step tool chaining over real biomedical data sources.

## Current Build Snapshot (Repo-Verified)

- Branding: `cpgAgent` has been fully rebranded to `LinkedOmicsChat`.
- Backend: FastAPI + SQLAlchemy with SQLite for development and PostgreSQL-ready production config.
- Orchestration: LangGraph-backed MCP orchestration with tool chaining and data-access guardrails.
- Frontend: Next.js 14 + Tailwind + shadcn/ui.
- Auth: registration, login, JWT auth, password reset, guest mode.
- Sessions: persistent chat history, paginated history loading, cross-session search, in-chat search.
- Visualization: Plotly charts render inline in chat, in the right-side context panel, and on shared read-only pages.
- Sharing: public read-only session links at `/shared/[token]`.
- Export: HTML export with embedded Plotly charts. Export now fetches session data directly so it works immediately after reload.
- Session actions: `Share` and `Export` are available as soon as a saved session is restored after reload.
- Docs: custom frontend docs page exists; default FastAPI Swagger docs exist; metadata is still minimal.
- Deployment scaffold: `docker-compose.yml` includes postgres/redis/ollama/backend/frontend; an nginx reverse-proxy block exists only as commented scaffold.

## Active MCP Servers (3 Servers / 16 Tools)

| Server | Live Tools | Status |
|--------|------------|--------|
| `linkedomics_server.py` | `funmap_neighborhood`, `get_target`, `batch_get_target`, `cancer_gene_expression`, `batch_cancer_gene_expression`, `overall_survival_per_cancer`, `batch_overall_survival_per_cancer`, `clinical_trial_information`, `batch_clinical_trial_information`, `get_cis_correlations`, `batch_get_cis_correlations`, `webgestalt`, `tcga_survival_analysis` | ✅ Live |
| `literature_server.py` | `search_pubmed`, `get_pubmed_abstract` | ✅ Live |
| `gene_utils_server.py` | `resolve_gene_identifier` | ✅ Live |

## What Is Already Done

### Platform And Orchestration
- FastAPI backend wired to LangGraph-backed MCP orchestration.
- MCP aggregator initializes multiple stdio MCP servers from repo-managed config.
- Data-access routing logic is explicitly encoded in the system prompt, including TCGA-vs-CPTAC guidance.

### Data And Tools
- LinkedOmics / FunMap / WebGestalt / PubMed / gene-identifier toolchain is live.
- `tcga_survival_analysis` is already available through `linkedomics_server.py`.
- Literature search has already moved to real PubMed integration instead of generic web search.

### UX And Frontend
- Shared read-only session pages are implemented and render Plotly charts.
- Right-side context panel can preview plots and jump back to the originating chat message.
- Chat history supports paginated loading and search across sessions.
- Share popup now opens immediately and supports copy-to-clipboard.
- Share/export controls are usable immediately after a saved session reloads.
- Export is now session-backed instead of only UI-state-backed, which avoids partial exports after refresh.

### Auth And Sessions
- Full auth flow is implemented.
- Guest mode exists with in-memory sessions and rate limiting.
- Session persistence, rename, delete, and search are implemented.

### Infra And Docs
- Docker Compose scaffold exists for local/prod-like stack bring-up.
- Deployment helper scripts exist (`deploy_aws.sh`, `deploy_rsync.sh`, `restart.sh`).
- A custom documentation page exists in the frontend.

## Plan Changes From The Previous Version

- Corrected the active tool inventory: the repo now exposes 16 MCP tools, not the smaller older set in the previous plan.
- Updated TCGA status: TCGA survival support already exists via `tcga_survival_analysis`; the remaining gap is a separate GDC mutation/clinical server, not TCGA access in general.
- Corrected export status: the current product supports HTML export with embedded charts; a separate Markdown export is not the primary live path.
- Marked session sharing, shared pages, Plotly rendering, and immediate post-reload session actions as complete.
- Reframed the highest-risk gaps away from core product UX and toward deployment hardening plus validation for publication.

## Current Gaps (NAR-Facing)

| Gap | Severity | Current Status |
|-----|----------|----------------|
| Public deployment is not standardized in repo | 🔴 Blocking | No repo-managed live domain/SSL setup; nginx in `docker-compose.yml` is commented out |
| No biological validation suite | 🟡 Required | No `backend/tests` validation or benchmark harness present |
| No formal case-study runner for paper figures | 🟡 Required | No scripted case-study outputs in repo |
| No standalone GDC mutation/clinical MCP server | 🟡 Important | TCGA survival is live, but mutation frequency and clinical case summaries are still missing |
| OpenAPI metadata is minimal | 🟢 Recommended | `backend/main.py` lacks `contact`, `license_info`, and `tags_metadata` |
| Paper-support assets are missing | 🟢 Recommended | No architecture diagram or comparison table in repo |
| Deployment runbook is incomplete | 🟢 Recommended | Compose exists, but reverse proxy / SSL / domain ownership are not documented as code |

## Recommended Priority Order

### 1. Public Deployment Hardening
This is still the biggest publication blocker.

Targets:
- Enable a repo-managed reverse proxy path.
- Add SSL termination and document certificate renewal.
- Standardize the production URL, CORS origins, and health-check path.
- Capture a reproducible deployment runbook in the repo.

Concrete repo work:
- Add or un-comment a real nginx service in `docker-compose.yml`, or document the existing Apache-based production pattern in repo-managed config.
- Add `nginx/nginx.conf` and, if applicable, TLS instructions.
- Add a short deployment README that explains the expected production topology.

### 2. Biological Validation And Case Studies
This is the highest-value scientific work now that the core app experience is already strong.

Targets:
- Build a small benchmark set of known biology questions.
- Define expected tool calls and expected directional answers.
- Produce reproducible outputs for 5 paper-quality case studies.

Suggested files:
- `backend/tests/test_biological_accuracy.py`
- `backend/tests/run_case_studies.py`
- `docs/case_studies/`

### 3. Paper Assets And API Polish
The repo is already good enough to support this phase.

Targets:
- Add OpenAPI `contact`, `license_info`, and `tags_metadata` in `backend/main.py`.
- Expand `frontend/app/docs/page.tsx` with Swagger/ReDoc links, citation text, and data-source attribution.
- Add an architecture diagram.
- Add a comparison table against LinkedOmics / cBioPortal / similar portals.

Suggested files:
- `docs/architecture_diagram.py`
- `docs/comparison_table.md`

### 4. GDC Expansion (Mutation + Clinical)
This is now an extension, not the immediate blocker it was in the older plan.

Rationale:
- The repo already supports TCGA survival queries through `tcga_survival_analysis`.
- What is still missing is direct GDC-backed mutation frequency and clinical metadata access.

Suggested implementation:
- `backend/mcp_servers/gdc_server.py`
- config flag in `backend/core/config.py`
- MCP registration in `backend/services/mcp_aggregator.py`
- prompt updates in `backend/services/langgraph_orchestrator.py`

Suggested first tools:
- `get_available_tcga_projects()`
- `get_tcga_mutation_frequency(gene, cancer_type)`
- `get_tcga_clinical_data(cancer_type)`

### 5. Nice-To-Have Product Polish
These are useful, but they should not outrank deployment or validation.

Ideas:
- Decide whether to reintroduce a separate Markdown export path.
- Add shared-link revocation or expiry controls.
- Add CI smoke tests for share/export and shared-page rendering.

## Immediate Next-Step Sequence

1. Freeze the current product surface for paper-facing work.
2. Finish deployment hardening so reviewers can access a stable public instance.
3. Build the biological validation suite.
4. Script 5 strong case studies and save their outputs.
5. Add paper-support assets and API metadata.
6. Only then decide whether GDC mutation/clinical expansion fits the submission timeline.

## Verification Checklist

### Current Product Smoke Tests
1. Reload a saved chat page: `Share` and `Export` are visible immediately.
2. Click `Share`: popup appears immediately and the copy button works.
3. Open the shared link in a logged-out browser: read-only session loads with Plotly charts.
4. Click `Export` right after reload: HTML report downloads successfully even before the visible history fully hydrates.
5. Ask a PubMed question: `search_pubmed` / `get_pubmed_abstract` path returns real literature data.
6. Ask a TCGA survival question for a non-CPTAC cohort: `tcga_survival_analysis` is selected.

### Pre-Submission Checklist
1. Public URL is stable and HTTPS-enabled.
2. Reverse proxy and SSL are documented in repo-managed config.
3. `backend/tests/test_biological_accuracy.py` exists and passes agreed thresholds.
4. `backend/tests/run_case_studies.py` generates the paper case studies reproducibly.
5. `/api/docs` includes contact/license/tags metadata.
6. Architecture diagram and comparison table are committed.

## Bottom Line
The project is no longer in an early product-build phase. The core app, multi-tool research workflow, sharing flow, and charting UX are already present. The real work left for an NAR submission is now:

- deployment hardening,
- scientific validation,
- case-study packaging,
- and publication-support documentation.
