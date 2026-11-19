# LinkedOmicsChat

A chat interface to LinkedOmics and related cancer resources. A question in plain English is turned into
analyses on TCGA and CPTAC multi-omics data, clinical-trial expression studies, drug-target annotations, the
FunMap network, and WebGestalt, and the answer comes back as the plots and tables those analyses produce, with a
short written summary.

Use it at **https://chat.linkedomics.org**; no account is needed. The
[documentation](https://chat.linkedomics.org/docs) has example questions and results, and explains how to read
them.

## How it works

A LangGraph agent decides which of 27 tools a question needs and calls them. The tools run on three MCP servers
and query the live services: TCGA and CPTAC data through LinkedOmics and LinkedOmicsKB, ClinicalOmicsDB,
LinkedOmics Targets, FunMap, WebGestalt, and PubMed. The plots and tables come straight from the tool output;
the language model writes only the summary. LinkedOmicsChat keeps no copy of the underlying data.

## Repository

`frontend/` is the Next.js app, `backend/` the FastAPI service and agent, and `backend/mcp_servers/` the tool
servers ([README](backend/mcp_servers/README.md)). Notes on running, testing, and deploying it are in
[DEVELOPMENT.md](DEVELOPMENT.md).

## Citation, license, and contact

There is no LinkedOmicsChat paper yet. If you use it in published work, please cite LinkedOmics:
Vasaikar SV, Straub P, Wang J, Zhang B. LinkedOmics: analyzing multi-omics data within and across 32 cancer
types. *Nucleic Acids Research*, 2018.

MIT License; see [LICENSE](LICENSE). Developed and maintained by the [Zhang Lab](https://www.zhang-lab.org).
Report problems or ask questions in [GitHub issues](https://github.com/bzhanglab/LinkedOmicsChat/issues).
