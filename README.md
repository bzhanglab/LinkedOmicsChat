# cpgAgent: Cancer Proteogenomics Agent

**cpgAgent** (Cancer Proteogenomics Agent) is a modern agentic platform that transforms traditional web-based omics analysis into an intelligent,
conversational, and autonomous research assistant for cancer proteogenomics research.

## Overview

cpgAgent (Cancer Proteogenomics Agent) modernizes multi-omics analysis by introducing:
- **Conversational AI Interface**: Natural language queries instead of complex UI navigation
- **Autonomous Agents**: Specialized AI agents for data curation, analysis, visualization, and literature mining
- **Multi-omics Data Support**: TCGA and CPTAC datasets for cancer proteogenomics research
- **Interactive Visualizations**: Publication-ready figures with Plotly and Recharts

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
- **LangChain** for LLM integration and agent orchestration
- **Pydantic** for data validation
- **SQLAlchemy** (async) with PostgreSQL for database
- **Redis** for caching (optional)
- **WebSockets** for real-time communication

### AI/ML
- **OpenAI GPT-4** / **Anthropic Claude** for language understanding
- **Ollama** for local LLM support (Llama 3, etc.)
- **Mock LLM mode** for development without API keys
- **Web search** integration for literature mining

## Features

### 1. Conversational Interface
- Natural language queries: "Show me genes correlated with TP53 in breast cancer"
- Multi-turn conversations with context awareness
- Chat history and session management

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
- Summarizes findings using web search
- Suggests related research directions

#### Association Agent
- Finds gene-gene correlations
- Analyzes gene-clinical feature associations
- Supports both TCGA and CPTAC datasets

#### Differential Expression Agent
- Identifies differentially expressed genes between groups
- Statistical analysis with p-values and FDR
- Supports multiple comparison methods

### 3. Data Sources
- **TCGA**: RNA-seq, clinical, and mutation data for multiple cancer types
- **CPTAC**: Proteomics and phosphoproteomics data
- Support for custom datasets via parquet files

### 4. Deployment
- **Local Development**: Simple setup scripts for macOS
- **Docker**: Containerized deployment with Docker Compose
- **AWS EC2**: Production deployment with automated setup scripts

## Development Without API Keys

You can start the application in mock mode without any API keys:

```bash
./setup_local_macos.sh    # Sets up mock mode by default
./start_backend.sh         # Terminal 1
./start_frontend.sh        # Terminal 2
# Open http://localhost:3000
```

Mock mode simulates AI responses for development and testing.

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
USE_OLLAMA=false
OLLAMA_MODEL=llama3
OLLAMA_BASE_URL=http://localhost:11434
MOCK_LLM=false
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
1. DataCurationAgent: Identified TCGA BRCA dataset
2. AssociationAgent: Computing Pearson correlations across genes...
3. VisualizationAgent: Creating scatter plots and heatmap...
4. Results: Top correlated genes with statistical significance
```

### Example 2: Differential Expression Analysis
```
User: "Find genes differentially expressed between stage I and stage IV in lung cancer"

cpgAgent:
1. DataCurationAgent: Retrieved TCGA LUAD dataset
2. DifferentialExpressionAgent: Running statistical tests...
3. VisualizationAgent: Generated volcano plot and heatmap
4. LiteratureAgent: Searching for relevant publications
```

## Development

### Local Development
```bash
# Start backend (Terminal 1)
./start_backend.sh

# Start frontend (Terminal 2)
./start_frontend.sh
```

### Code Quality
```bash
# Frontend linting
cd frontend
npm run lint
npm run type-check
```

## Deployment

### Docker Deployment
```bash
# Build and start all services
docker compose up -d --build

# View logs
docker compose logs -f

# Stop services
docker compose down
```

### AWS EC2 Deployment
Use the automated deployment script:
```bash
./deploy_aws.sh
```

The script will guide you through the setup process, including Docker installation, environment configuration, and service startup.

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

## Documentation

The project includes setup scripts and configuration files for easy deployment:
- `setup_local_macos.sh` - One-command local development setup
- `deploy_aws.sh` - Automated AWS EC2 deployment
- `docker-compose.yml` - Docker container orchestration
- `start_backend.sh` / `start_frontend.sh` - Service startup scripts

## Acknowledgments

cpgAgent (Cancer Proteogenomics Agent) brings modern AI capabilities to cancer proteogenomics and multi-omics research, enabling researchers to analyze complex biological data through natural language interactions.
