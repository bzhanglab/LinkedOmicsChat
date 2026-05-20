# LinkedOmicsChat

**LinkedOmicsChat** is an AI-powered conversational interface for multi-omics cancer research. Ask natural-language questions about gene expression, survival, methylation, copy number, and protein abundance across TCGA and CPTAC cohorts — and receive publication-ready plots, ranked tables, and LLM-generated summaries in a single chat turn.

- **Live app**: _coming soon_
- **About / data sources**: `/about` page in the app
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
- **Guest mode** — try without registration; rate-limited to 20 queries/hour

---

## Data Sources

All data are retrieved in real time from [LinkedOmics](https://www.linkedomics.org) — no raw data is stored by this application.

| Source | Description |
|--------|-------------|
| [TCGA](https://www.cancer.gov/tcga) | 11,000+ tumor samples across 32 cancer types; mRNA, miRNA, methylation, SCNA, RPPA |
| [CPTAC](https://proteomics.cancer.gov/programs/cptac) | 10 cohorts; mass spectrometry proteomics and phosphoproteomics |

---

## Tech Stack

### Backend
- **FastAPI** + **SQLAlchemy** (async, SQLite/PostgreSQL)
- **LangGraph** for LLM orchestration
- **MCP** ([Model Context Protocol](https://modelcontextprotocol.io)) for tool routing
- **lifelines**, **scipy**, **matplotlib** for statistical analysis and plot generation
- **JWT** authentication with bcrypt password hashing

### Frontend
- **Next.js 14+** (App Router) + **TypeScript**
- **Tailwind CSS** + **shadcn/ui**
- **ReactMarkdown** + **KaTeX** for rich response rendering

### LLM Support
- Google Gemini, OpenAI, Anthropic Claude (configurable via `DEFAULT_LLM_MODEL`)
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
MOCK_LLM=false
DEFAULT_LLM_MODEL=gemini-3-flash-preview   # or gpt-4o, claude-opus-4-6, etc.
GOOGLE_API_KEY=your-key-here               # or OPENAI_API_KEY / ANTHROPIC_API_KEY
DATABASE_URL=sqlite:///./linkedomicsai.db
DEBUG=True
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
| `DEFAULT_LLM_MODEL` | `gemini-3-flash-preview` | LLM model name |
| `GOOGLE_API_KEY` | — | Google Gemini API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `MOCK_LLM` | `false` | Use mock responses (no key needed) |
| `DATABASE_URL` | `sqlite:///./linkedomicsai.db` | Database connection string |
| `DEBUG` | `false` | Enable auto-reload (dev only) |
| `GUEST_RATE_LIMIT_PER_HOUR` | `20` | Max guest queries per hour |

### Frontend (`frontend/.env.local`)

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend base URL |

---

## Deployment

### Docker

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
