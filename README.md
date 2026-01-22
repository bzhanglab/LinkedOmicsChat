# cpgAgent: Cancer Proteogenomics Agent

**cpgAgent** (Cancer Proteogenomics Agent) is a modern agentic platform that transforms traditional web-based omics analysis into an intelligent,
conversational, and autonomous research assistant for cancer proteogenomics research.

## Overview

cpgAgent (Cancer Proteogenomics Agent) modernizes multi-omics analysis by introducing:
- **Conversational AI Interface**: Natural language queries instead of complex UI navigation
- **Autonomous Agents**: Specialized AI agents for data curation, analysis, visualization, and interpretation
- **Intelligent Workflows**: Auto-generated analysis pipelines based on research questions
- **Real-time Collaboration**: Multi-user support with live updates
- **Publication-Ready Outputs**: Automated figure generation and analysis documentation

## Architecture

```
cpgAgent/
├── backend/              # FastAPI backend with agent orchestration
│   ├── agents/          # Specialized AI agents
│   ├── api/             # REST API endpoints
│   ├── core/            # Core business logic
│   └── services/        # External service integrations
├── frontend/            # Next.js 14+ React application
│   ├── app/            # App router pages
│   ├── components/     # Reusable UI components
│   └── lib/            # Utilities and hooks
├── shared/             # Shared types and schemas
└── docs/               # Documentation and architecture
```

## Tech Stack

### Frontend
- **Next.js 14+** with App Router and Server Components
- **TypeScript** for type safety
- **Tailwind CSS + shadcn/ui** for modern, accessible UI
- **React Flow** for workflow visualization
- **Recharts/Plotly** for interactive visualizations
- **Zustand** for state management

### Backend
- **FastAPI** for high-performance Python API
- **LangGraph** for agent orchestration
- **LangChain** for LLM integration
- **Pydantic** for data validation
- **SQLAlchemy** for database ORM
- **Redis** for caching and pub/sub
- **Celery** for background tasks

### AI/ML
- **OpenAI GPT-4** / **Anthropic Claude** for language understanding
- **LlamaIndex** for RAG over scientific literature
- **Vector Database** (Pinecone/Weaviate) for semantic search
- **Instructor** for structured LLM outputs

## Features

### 1. Conversational Interface
- Natural language queries: "Show me genes correlated with TP53 in breast cancer"
- Multi-turn conversations with context awareness
- Voice input support

### 2. Specialized Agents

#### Data Curation Agent
- Discovers relevant datasets based on research questions
- Validates data quality
- Suggests appropriate preprocessing steps

#### Statistical Analysis Agent
- Recommends statistical tests based on data characteristics
- Executes analyses with proper controls
- Interprets results in biological context

#### Visualization Agent
- Auto-generates publication-ready figures
- Adapts visualization to data type and research question
- Supports interactive exploration

#### Literature Agent
- Mines relevant papers for discovered patterns
- Summarizes findings
- Suggests related research directions

#### Interpretation Agent
- Explains results in plain language
- Provides biological context
- Highlights significant findings

### 3. Workflow Management
- Auto-generated analysis pipelines
- Version control for analyses
- Reproducible research with auto-documentation
- Export to R/Python scripts or Jupyter notebooks

### 4. Collaboration
- Real-time multi-user editing
- Shared workspaces
- Comments and annotations
- Team dashboards

## 🚀 No API Key? No Problem!

**Start immediately without any API key** using mock mode:

```bash
./setup_local_macos.sh    # Sets up mock mode by default
./start_backend.sh         # Terminal 1
./start_frontend.sh        # Terminal 2
# Open http://localhost:3000 - Everything works!
```

Mock mode simulates AI responses so you can develop the full UI and test the architecture without any costs.

📖 **See**: [START_WITHOUT_API_KEY.md](START_WITHOUT_API_KEY.md) | [DEVELOPMENT_WITHOUT_OPENAI.md](docs/DEVELOPMENT_WITHOUT_OPENAI.md)

---

## Quick Start

### 🍎 Local Development on macOS (Recommended)

**One-command setup:**

```bash
./setup_local_macos.sh
```

This script will:
- ✓ Check prerequisites (Python, Node.js)
- ✓ Set up Python virtual environment
- ✓ Install all backend dependencies
- ✓ Install all frontend dependencies
- ✓ Create configuration files

**Then start the services:**

```bash
# Terminal 1 - Backend
./start_backend.sh

# Terminal 2 - Frontend
./start_frontend.sh
```

**That's it!** Open `http://localhost:3000` and start using cpgAgent.

📖 **Detailed guide**: See [docs/LOCAL_DEVELOPMENT_MACOS.md](docs/LOCAL_DEVELOPMENT_MACOS.md)

---

### Manual Setup (All Platforms)

#### Prerequisites
- Python 3.11+
- Node.js 20+
- Redis (optional, for caching)
- PostgreSQL (optional, for production)

#### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Create .env file
cat > .env << EOF
OPENAI_API_KEY=your-key-here
DATABASE_URL=sqlite:///./cpgagent.db
ENVIRONMENT=development
DEBUG=True
EOF

# Run the server
python main.py
```

Backend runs at `http://localhost:8000`

#### Frontend Setup

```bash
cd frontend
npm install

# Create .env.local file
cat > .env.local << EOF
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
EOF

# Run the development server
npm run dev
```

Frontend runs at `http://localhost:3000`

## Environment Variables

### Backend (.env)
```
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
DATABASE_URL=postgresql://user:pass@localhost/cpgagent
REDIS_URL=redis://localhost:6379
ENVIRONMENT=development
```

### Frontend (.env.local)
```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

## Usage Examples

### Example 1: Gene Correlation Analysis
```
User: "Find genes correlated with TP53 expression in breast cancer"

cpgAgent:
1. DataAgent: Found 3 relevant breast cancer datasets (TCGA, METABRIC, GEO)
2. AnalysisAgent: Computing Pearson correlations across 20,000 genes...
3. VizAgent: Creating scatter plots and heatmap...
4. InterpretationAgent: Top correlated genes include MDM2 (r=0.85),
   involved in p53 pathway regulation...
```

### Example 2: Survival Analysis
```
User: "Perform survival analysis for top differentially expressed genes in lung cancer"

cpgAgent:
1. DataAgent: Retrieved TCGA lung cancer cohort (n=1,016 patients)
2. AnalysisAgent: Identified 156 DEGs (FDR < 0.05)
3. AnalysisAgent: Running Cox regression for top 50 genes...
4. VizAgent: Generated Kaplan-Meier plots and forest plot
5. LiteratureAgent: Found 12 papers validating EGFR as prognostic marker
```

## Development

### Running Tests
```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

### Code Quality
```bash
# Backend linting
cd backend
ruff check .
black .

# Frontend linting
cd frontend
npm run lint
```

## Deployment

See [DEPLOYMENT.md](./docs/DEPLOYMENT.md) for production deployment instructions.

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](./docs/CONTRIBUTING.md) for details.

## License

MIT License - see [LICENSE](./LICENSE) for details.

## Citation

If you use cpgAgent in your research, please cite:
```bibtex
@software{cpgagent2026,
  title={cpgAgent: Cancer Proteogenomics Agent - Modern Agentic Platform for Multi-Omics Analysis},
  author={Zhang Lab},
  year={2026},
  url={https://github.com/zhanglab/cpgagent}
}
```

## Support

- Documentation: [https://cpgagent.readthedocs.io](https://cpgagent.readthedocs.io)
- Issues: [GitHub Issues](https://github.com/zhanglab/cpgagent/issues)
- Email: support@cpgagent.org

## Acknowledgments

cpgAgent (Cancer Proteogenomics Agent) brings modern AI capabilities to cancer proteogenomics and multi-omics research, enabling researchers to analyze complex biological data through natural language interactions.
