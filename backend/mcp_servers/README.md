# MCP Servers

This directory contains MCP (Model Context Protocol) servers for LinkedOmicsChat.

## Server Structure

### Data Server (`data_server.py`)
Provides data access tools:
- Gene/protein information
- TCGA/CPTAC dataset access
- Clinical data queries
- Sample mapping

### Files Server (`files_server.py`)
Provides file operations:
- Read/write files
- Index and search
- Artifact storage
- PDF/results management

### Compute Server (`compute_server.py`)
Provides compute/HPC operations:
- SLURM job submission
- Nextflow pipeline execution
- Container management
- Job monitoring

## Running MCP Servers

Each server can be run as a standalone process:

```bash
# Data Server
python -m backend.mcp_servers.data_server

# Files Server
python -m backend.mcp_servers.files_server

# Compute Server
python -m backend.mcp_servers.compute_server
```

## Development

Servers are developed incrementally during migration phases:
- Phase 1: Basic Data Server structure
- Phase 2: Full Data Server implementation
- Phase 3: Files and Compute Servers
