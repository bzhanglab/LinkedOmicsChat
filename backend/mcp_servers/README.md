# MCP tool servers

These are the three FastMCP servers behind LinkedOmicsChat's 26 tools. The backend never keeps them running:
`services/mcp_aggregator.py` starts the relevant server as a stdio subprocess for each tool call and lets it
exit afterwards. Changes to a server file therefore take effect on the next call, without restarting the
backend; in Docker, `backend/` is bind-mounted, so the same is true there. The cost is about 0.6–0.8 s of
server startup per call.

Which servers load is controlled in `backend/.env` (or the root `.env` under Docker). `USE_MCP=true` is required,
and `MCP_LINKEDOMICS_SERVER_ENABLED=true` must be set because it defaults to off. `MCP_GENE_UTILS_SERVER_ENABLED`
and `MCP_LITERATURE_SERVER_ENABLED` default to on.

**`linkedomics_server.py`** (23 tools) wraps the LinkedOmics family of APIs plus FunMap and WebGestalt:

- TCGA through LinkedOmics: `analyze_tcga_survival_associations` and `analyze_tcga_cis_associations`. Both
  have several modes, from a single gene in one cohort up to genome-wide scans.
- CPTAC through LinkedOmicsKB: `compare_cptac_tumor_normal_expression`,
  `analyze_cptac_gene_survival_associations`, and `analyze_cptac_cis_associations`, each with a `batch_` version
  for gene lists.
- LinkedOmics Targets: `get_drug_target_profile` and its batch version, `search_drug_target_index`, and
  `rank_drug_targets`. The full target index is cached in `data/cache/targets_index.json` for 24 hours; if a
  refresh fails, the stale copy is used.
- ClinicalOmicsDB: `search_gene_response_trials` (and its batch version), `search_gene_set_response_trials`,
  `search_trial_studies`, `get_trial_study_details`, `rank_study_response_genes`,
  `rank_study_response_gene_sets`, `meta_analyze_response_genes`, and `meta_analyze_response_gene_sets`.
  Direction follows the ClinicalOmicsDB convention: AUROC below 0.5 means higher expression goes with better
  response. The docstrings spell this out because the model gets it wrong otherwise.
- `get_funmap_functional_neighborhood` returns a gene's top 50 FunMap neighbors by random-walk probability.
  `run_webgestalt_go_enrichment` runs Gene Ontology biological-process over-representation analysis on a gene
  list.

**`gene_utils_server.py`** (1 tool) has `resolve_gene_identifier`, which converts Ensembl gene IDs and UniProt
accessions to HGNC symbols through MyGene.info (`gene_converter.py`). Input that is already a gene symbol is
checked against `valid_genes.txt` at the repository root instead. Inside the Docker container that path does not
exist (only `backend/` is mounted), so the symbol check is silently skipped in production.

**`literature_server.py`** (2 tools) has `search_pubmed_articles` and `get_pubmed_article_details`, through NCBI
E-utilities. Setting `NCBI_EMAIL` is recommended by NCBI's terms; `NCBI_API_KEY` raises the rate limit from 3 to
10 requests a second.

## Adding or changing a tool

A tool is a function decorated with `@mcp.tool` in one of these files. Its docstring is the description the
model reads when deciding what to call, so write it for the model: when to use the tool, what each argument
means, and how to read the result. Then:

1. Add it to the relevant tool groups in `_TOOL_SCOPE_MAP` in `services/langgraph_orchestrator.py`. The
   keyword router offers the model only the tools in the group a question matches; a tool in no group is
   offered only when a question matches several groups, or none, and the router falls back to the full set.
2. If its output is large, add a compaction rule in `_compact_tool_message` in the same file, because the
   model sees the compacted version. Everything over 100,000 characters is trimmed regardless.
3. For a table or plot in the chat, add a renderer in `_format_linkedomics_results` in
   `services/mcp_orchestrator.py`.
4. In `frontend/components/ToolExplorer.tsx`, add an example input to `TOOL_EXAMPLE_ARGS` (used by the Tools
   view and by `admin/check_tools.py`) and a plain name and one-line summary to `TOOL_DISPLAY` (without one, the
   Tools view shows the function name). Add a data-source entry in `frontend/lib/toolCategories.ts`.
5. Add a sentence for it to `SENTENCES` in `frontend/lib/methodsExport.ts`, naming the resource it cites; without
   one, the methods text export describes it only as "also used".
6. If it analyzes one gene, it can be repeated for other genes: add it to `_GENE_ARG` in
   `services/repeat_workflow.py` (and its batch tool to `_BATCH_OF`), give it a column name in `_LABELS` and a
   cell summary in `_HEADLINES`, and add it to `GENE_ARG` (or `BATCH_TOOLS`) in `frontend/lib/repeat.ts`.

Each server also runs on its own (`venv/bin/python mcp_servers/literature_server.py`), but it then just waits
for an MCP client on stdin. In practice it is easier to try a tool through the app's Tools view or
`POST /api/v1/tools/execute`, and to check them all with `admin/check_tools.py`.
