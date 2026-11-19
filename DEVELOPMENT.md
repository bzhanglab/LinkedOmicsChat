# Development notes

Notes for working on LinkedOmicsChat. The app is run by the Zhang Lab at https://chat.linkedomics.org, so this
is a guide to the code and our own deployment, not a self-hosting guide.

## How it is put together

The frontend (`frontend/`) is Next.js 14. The backend (`backend/`) is FastAPI, with a LangGraph agent that
answers questions by calling 27 tools from three MCP servers in `backend/mcp_servers/`: 24 analyses on the
LinkedOmics family of APIs, FunMap, and WebGestalt, one gene ID converter, and two PubMed tools. The
aggregator (`backend/services/mcp_aggregator.py`) starts the relevant server as a short-lived stdio process
for every tool call, so edits to a server file take effect on the next call. See
[backend/mcp_servers/README.md](backend/mcp_servers/README.md) for the servers and how to add a tool.

Before the model sees a question, a keyword router (`_TOOL_SCOPE_MAP` and friends in
`backend/services/langgraph_orchestrator.py`) picks the relevant group of tools, and Ensembl or UniProt IDs
are converted to gene symbols. Every tool call is checked against the genes in the question plus genes
returned earlier in the same answer; calls on any other gene are blocked. Plots and tables are built from the
tool output by `backend/services/mcp_orchestrator.py` (static plots with matplotlib, interactive tables,
grids, and networks in the frontend), and the written summary is a separate model call over the same results.

Some features work around the agent. An attached gene list is checked by `backend/services/gene_list.py`
(`POST /api/v1/chat/gene-list`: it finds the gene column, checks symbols against `valid_genes.txt`, converts IDs
and old names in one batched MyGene.info request, and keeps at most 2,000 genes) and is sent with each question.
The model passes the placeholder `MY_LIST`, and the tool step swaps in the whole list for WebGestalt and the first
50 genes for the per-gene batch tools; long batches get one combined heatmap or plots for their first 10 genes. A
gene report ("Report on <gene>", matched by `_parse_gene_report_request` in `langgraph_orchestrator.py`) runs the
seven calls in `_gene_report_calls` at once and builds the answer from them without the agent. A repeat
("Repeat for other genes" on an answer) sends `repeat` with the request: the answer's tool calls and up to 10
genes. `plan_repeat` in `backend/services/repeat_workflow.py` keeps the calls about one gene, using the batch
tool where there is one, and `_run_direct_tool_calls` runs them without the model (at most two TCGA calls at
once, since the TCGA service fails under more, and failed calls get one retry). The answer has no summary;
`combined_table` puts a table with one row per gene above the usual plots.

Treatment response matching (`match_signature_to_treatment_response`) tests a list against every
ClinicalOmicsDB study. `backend/mcp_servers/signature_matching.py` keeps each study's full gene ranking (AUROC per
gene) as one matrix in `backend/data/cache/clinicalomicsdb/`, with old gene names mapped to current symbols. The
backend refreshes it in the background at startup when it is missing or a week old (about 1.5 minutes;
`python mcp_servers/signature_matching.py --refresh` does it by hand), and tool calls return "unavailable" until
the first copy exists. In each study the list's genes are compared with all other measured genes (Mann-Whitney;
the score is the rank-biserial correlation). That gene-level p alone overstates co-expressed signatures, so the
p used is the larger of it and a patient-level p from the AUROC the score implies (`_AUC_SCALE`,
`_AUC_STEEPNESS`, fitted on the 50 Hallmark sets against ClinicalOmicsDB's own patient-level gene-set results),
then Benjamini-Hochberg across studies. Refit those two constants if the ClinicalOmicsDB studies change much.

After every summary, `backend/services/number_check.py` looks for each of its numbers in the tool results and
returns the summary with the numbers marked for the frontend.

Each answer sent to the browser, live or from the chat history, includes its tool calls and their inputs
(`tool_calls`), which the Python script and methods text exports (`frontend/lib/pythonExport.ts` and
`frontend/lib/methodsExport.ts`) and the repeat are built from. The references the methods text cites are
`REFERENCES` in `methodsExport.ts`; the About page keeps its own copy.

The LLM is chosen from `DEFAULT_LLM_MODEL` in `backend/core/llm_factory.py`: a name containing `claude` uses
Anthropic and one containing `gemini` uses Google; anything else goes to OpenAI. `USE_OLLAMA=true` switches to a
local Ollama model and `MOCK_LLM=true` returns canned responses. Production runs `claude-haiku-5-5`. No
temperature is sent to Claude, because current Claude models reject a non-default value.

Chats are stored in SQLite locally and in Postgres under Docker. There is no migration framework: missing
columns are added at startup by `backend/core/database.py`, so a new column needs an entry there for both
databases. `backend/migrations/` holds older one-off scripts.

## Running it locally

You need Python 3.11 (what Docker uses; 3.12 also works) and Node 20. `./setup_local_macos.sh` creates
`backend/venv`, installs the Python and npm dependencies, and writes a starter `backend/.env` and
`frontend/.env.local`. The starter `.env` runs in mock mode and leaves the LinkedOmics server off, so for real
answers change it to something like:

```bash
MOCK_LLM=false
DEFAULT_LLM_MODEL=claude-haiku-5-5        # or gemini-2.5-flash
ANTHROPIC_API_KEY=...                     # or GOOGLE_API_KEY
MAX_TOKENS=16000
USE_MCP=true
MCP_LINKEDOMICS_SERVER_ENABLED=true
```

Without the last two lines only the gene ID and PubMed servers load (3 of the 27 tools). Keep `MAX_TOKENS`
well above the 4000 default: for models that think before answering, the thinking counts against the limit,
and a low limit cuts answers short without an error.

Then `./start_backend.sh` (http://localhost:8000, API docs at `/docs`) and `./start_frontend.sh`
(http://localhost:3000), or `./start_all.sh` to run both in the background with logs in `logs/`, and
`./stop_all.sh` to stop them. The backend reloads on code changes. Environment variables override
`backend/.env`, which is handy for trying another model without editing the file. `frontend/.env.local` only
needs `NEXT_PUBLIC_API_URL`, and the frontend falls back to `http://localhost:8000` on localhost anyway.

Docker installs the exact versions in `backend/requirements.lock`; `requirements.txt` keeps looser pins, with
comments on the ones that matter (`mcp<2`, because the servers use `mcp.server.fastmcp`, which mcp 2.x
removed). After changing `requirements.txt`, regenerate the lock with the command at the top of
`requirements.lock`.

## Checking changes

There is no unit-test suite; three scripts in `backend/admin/` cover what matters:

```bash
cd backend
venv/bin/python admin/check_tools.py                    # runs all 27 tools once against http://localhost:8000
venv/bin/python admin/check_tools.py --base-url https://chat.linkedomics.org
venv/bin/python admin/langgraph_eval.py                 # 50 golden questions
venv/bin/python admin/langgraph_eval.py --case cis_and_enrichment --verbose
venv/bin/python admin/check_numbers.py                  # the number check, on 60 saved answers
venv/bin/python admin/check_numbers.py --collect        # ask those 60 questions again and save the answers
```

`check_tools.py` uses the same example inputs as the app's Tools view (`TOOL_EXAMPLE_ARGS` in
`frontend/components/ToolExplorer.tsx`). `langgraph_eval.py` runs the questions in
`backend/examples/langgraph_golden_queries.json` through the real model and checks which tools the agent
calls, not the wording of the answer. A full run takes about 14 minutes and costs about $0.40 with Claude Haiku;
prefix it with `DEFAULT_LLM_MODEL=...` to compare models. `usage_report.py` prints per-user token use, and
`check_prepopulated_genes.py` validates the gene symbols in the frontend's example questions.

Run `check_numbers.py` before changing `backend/services/number_check.py`. It fails if any number in the saved
answers comes out "not found" (they were reviewed and have none) or if too few made-up numbers planted in them
are flagged (80% in summaries; 45% in answers with literature, whose text the agent writes and whose many results
let more made-up numbers match some value by chance), and it checks 20 number formats. The answers live in `backend/data/number_check_cases/`,
which git ignores (about 36 MB); `--collect` rebuilds them for about $0.40, after which any new "not found"
needs a look by hand.

## Deployment

`docker-compose.yml` runs Postgres, the backend, and the frontend. It also starts Redis, which the current code
does not use, and Ollama, which is used only with `USE_OLLAMA=true`. Compose reads the `.env` next to it (the
repository root), not `backend/.env`, and passes it to the backend through `env_file`. After editing it, run
`docker compose up -d backend`; a plain `restart` keeps the old environment. The backend container bind-mounts
`./backend`, so it runs whatever code is on disk; the frontend is built into its image.

Production is an AWS EC2 host. `setup_ec2.sh` bootstraps a fresh instance once; after that, `deploy_rsync.sh`
syncs the working tree and rebuilds the containers (`docker compose build && docker compose up -d`). It reads
`LINKEDOMICSCHAT_AWS_HOST`, `LINKEDOMICSCHAT_AWS_KEY`, and `LINKEDOMICSCHAT_REMOTE_PATH` (see
`deploy_config.sh.example`), skips git-ignored files and all `.env` files, and with `LINKEDOMICSCHAT_DRY_RUN=true`
only lists what it would sync. Because it copies the working tree as it is, a real deploy stops unless you are on
`main`, nothing is uncommitted or untracked, and `main` has been pushed; dry runs only warn, and
`LINKEDOMICSCHAT_DEPLOY_ANY_BRANCH=true` skips the check for emergencies. Tagging the running images before a deploy
(`docker tag <image> linkedomicschat-backend:rollback-<date>`) makes rolling back a one-liner.
