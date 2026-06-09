# LinkedOmicsChat

**LinkedOmicsChat** is an AI-powered conversational interface for multi-omics cancer research. Ask natural-language questions about gene expression, survival, methylation, copy number, and protein abundance across TCGA and CPTAC cohorts — and receive publication-ready plots, ranked tables, and LLM-generated summaries in a single chat turn.

- **Live app**: [https://chat.linkedomics.org](https://chat.linkedomics.org)
- **About / data sources**: [About](https://chat.linkedomics.org/about) and [Documentation](https://chat.linkedomics.org/docs)
- **Issues / feedback**: [GitHub Issues](https://github.com/bzhanglab/LinkedOmicsChat/issues)

---

## Features

- **Conversational queries** — plain-English questions, no coding required
- **Kaplan-Meier survival analysis** — with hazard ratio, log-rank p-value, and scrollable at-risk table
- **Volcano plots** — tumor vs. normal differential expression
- **Correlation analysis** — gene-level Spearman/Pearson across omics layers
- **Network & pathway** — FunMap neighborhood and WebGestalt enrichment
- **Proteogenomics** — CPTAC mass-spec proteomics and phosphoproteomics integrated with TCGA
- **Session history** — chat history persisted per user with shareable links and HTML export
- **Guest mode** — try without registration; hourly limits are configurable

---

## Data Sources

Core omics data are accessed in real time through [LinkedOmics](https://www.linkedomics.org) and LinkedOmics-hosted APIs. Supporting workflows also call external services such as FunMap, WebGestalt, PubMed, and MyGene.info. LinkedOmicsChat does not store or redistribute raw omics data.

| Source | Description |
|--------|-------------|
| [LinkedOmics](https://www.linkedomics.org) / [TCGA](https://www.cancer.gov/tcga) | TCGA multi-omics analyses across 11,000+ tumor samples and 32 primary cancer types; includes mRNA, miRNA, methylation, SCNA, RPPA, and clinical data |
| [CPTAC](https://proteomics.cancer.gov/programs/cptac) | 10 tumor cohorts with mass spectrometry proteomics and phosphoproteomics integrated with TCGA genomic data |
| [FunMap](https://funmap.linkedomics.org) | Functional proteogenomic neighborhoods for network-based gene interpretation |
| [WebGestalt](https://www.webgestalt.org) | Gene set enrichment analysis for pathways, processes, and functional categories |
| [PubMed](https://pubmed.ncbi.nlm.nih.gov) / [MyGene.info](https://mygene.info) | Literature retrieval and gene identifier normalization |

---

## Tech Stack

### Backend
- **FastAPI** + **SQLAlchemy** (async, SQLite/PostgreSQL)
- **LangGraph** for LLM orchestration
- **MCP** ([Model Context Protocol](https://modelcontextprotocol.io)) for tool routing
- **lifelines**, **scipy**, **matplotlib** for statistical analysis and plot generation
- **JWT** authentication with bcrypt password hashing

### Frontend
- **Next.js 14.1** (App Router) + **TypeScript**
- **Tailwind CSS** + **shadcn/ui**
- **ReactMarkdown** + **KaTeX** for rich response rendering

### LLM Support
- Google Gemini, OpenAI, Anthropic Claude, and Ollama (configurable via `DEFAULT_LLM_MODEL` / `USE_OLLAMA`)
- Mock LLM mode for development without API keys

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 20+

### macOS (one command)

```bash
./setup_local_macos.sh
```

Then start the services in two terminals:

```bash
./start_backend.sh    # Terminal 1 — http://localhost:8000
./start_frontend.sh   # Terminal 2 — http://localhost:3000
```

### Manual Setup

**Backend:**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cat > .env << EOF
MOCK_LLM=true
DEFAULT_LLM_MODEL=gpt-4-turbo-preview
DATABASE_URL=sqlite:///./linkedomicsai.db
DEBUG=True

# To use a real provider, set MOCK_LLM=false and add one provider key:
# OPENAI_API_KEY=your-key-here
# GOOGLE_API_KEY=your-key-here
# ANTHROPIC_API_KEY=your-key-here
EOF

python main.py
```

**Frontend:**
```bash
cd frontend
npm install

cat > .env.local << EOF
NEXT_PUBLIC_API_URL=http://localhost:8000
EOF

npm run dev
```

### Mock mode (no API key needed)

Set `MOCK_LLM=true` in `backend/.env` to run with simulated LLM responses.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_LLM_MODEL` | `gpt-4-turbo-preview` | LLM model name |
| `GOOGLE_API_KEY` | — | Google Gemini API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `USE_OLLAMA` | `false` | Use a local Ollama model instead of a hosted provider |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |
| `MOCK_LLM` | `true` | Use mock responses (Docker overrides this to `false` unless set) |
| `DATABASE_URL` | `sqlite:///./linkedomicsai.db` | Database connection string |
| `DEBUG` | `true` | Enable auto-reload (dev only; Docker sets `false`) |
| `GUEST_RATE_LIMIT_ENABLED` | `true` | Enable hourly guest query limits |
| `GUEST_RATE_LIMIT_PER_HOUR` | `2` | Max guest queries per hour when guest limits are enabled |

### Frontend (`frontend/.env.local`)

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | local: `http://localhost:8000`; hosted: same-origin when unset | Backend base URL |

---

## Deployment

### Docker

Create a root `.env` first (or let `./setup_ec2.sh` generate one on a server). For a local mock deployment:

```bash
cat > .env << EOF
DB_PASSWORD=change-me
MOCK_LLM=true
CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
EOF
```

```bash
docker compose up -d --build
docker compose logs -f
```

### AWS EC2

```bash
./setup_ec2.sh           # One-time setup on a fresh EC2 instance
./deploy_rsync.sh        # Fast incremental updates from your local machine
```

For normal updates to an already configured server, use `deploy_rsync.sh`.

Set connection details before deploying:

```bash
export LINKEDOMICSCHAT_AWS_HOST="ec2-user@your-instance-ip"
export LINKEDOMICSCHAT_AWS_KEY="~/.ssh/your-key.pem"
export LINKEDOMICSCHAT_REMOTE_PATH="~/LinkedOmicsChat"
./deploy_rsync.sh
```

Use `LINKEDOMICSCHAT_DRY_RUN=true ./deploy_rsync.sh` to preview changes before syncing.

---

## Citation

If you use LinkedOmicsChat in your research, please cite _(citation pending publication)_.

Also cite the LinkedOmics resource:

> Vasaikar SV, Straub P, Wang J, Zhang B. LinkedOmics: analyzing multi-omics data within and across 32 cancer types. *Nucleic Acids Research*, 2018.

---

## License

MIT License — see [LICENSE](./LICENSE) for details.

Developed and maintained by the [Zhang Lab](https://www.zhang-lab.org).
