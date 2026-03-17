"""
Example workflow definitions for LinkedOmicsChat.
These can be imported or used as templates.
"""

correlation_workflow = {
    "name": "Gene Correlation Analysis",
    "description": "Find genes correlated with a target gene and visualize results",
    "steps": [
        {
            "step_id": "step_1",
            "agent_type": "data_curation",
            "action": "find datasets with RNA-seq data for specified cancer type",
            "parameters": {
                "data_type": "rna_seq",
                "required_samples": 100
            },
            "dependencies": []
        },
        {
            "step_id": "step_2",
            "agent_type": "statistical_analysis",
            "action": "perform correlation analysis with target gene",
            "parameters": {
                "method": "pearson",
                "correction": "fdr",
                "threshold": 0.05
            },
            "dependencies": ["step_1"]
        },
        {
            "step_id": "step_3",
            "agent_type": "visualization",
            "action": "create correlation visualizations",
            "parameters": {
                "plot_types": ["scatter", "heatmap", "network"]
            },
            "dependencies": ["step_2"]
        },
        {
            "step_id": "step_4",
            "agent_type": "literature_mining",
            "action": "find papers about top correlated genes",
            "parameters": {
                "top_n": 10
            },
            "dependencies": ["step_2"]
        }
    ],
    "expected_duration": "5-10 minutes",
    "outputs": [
        "List of correlated genes with statistics",
        "Scatter plots and heatmaps",
        "Literature summaries"
    ]
}

survival_workflow = {
    "name": "Survival Analysis Pipeline",
    "description": "Perform comprehensive survival analysis with visualization and validation",
    "steps": [
        {
            "step_id": "step_1",
            "agent_type": "data_curation",
            "action": "find datasets with clinical survival data",
            "parameters": {
                "required_fields": ["survival_time", "vital_status"],
                "min_patients": 200
            },
            "dependencies": []
        },
        {
            "step_id": "step_2",
            "agent_type": "statistical_analysis",
            "action": "perform Cox regression and log-rank test",
            "parameters": {
                "stratification": "median_split",
                "covariates": ["age", "stage"]
            },
            "dependencies": ["step_1"]
        },
        {
            "step_id": "step_3",
            "agent_type": "visualization",
            "action": "create Kaplan-Meier curves and forest plots",
            "parameters": {
                "show_risk_table": True,
                "confidence_intervals": True
            },
            "dependencies": ["step_2"]
        },
        {
            "step_id": "step_4",
            "agent_type": "literature_mining",
            "action": "search for prognostic studies of target gene",
            "parameters": {
                "search_terms": ["prognosis", "survival", "biomarker"]
            },
            "dependencies": ["step_2"]
        }
    ],
    "expected_duration": "10-15 minutes",
    "outputs": [
        "Hazard ratios and p-values",
        "Kaplan-Meier survival curves",
        "Literature validation"
    ]
}

differential_expression_workflow = {
    "name": "Differential Expression Analysis",
    "description": "Compare gene expression between groups with pathway enrichment",
    "steps": [
        {
            "step_id": "step_1",
            "agent_type": "data_curation",
            "action": "find datasets with appropriate sample groups",
            "parameters": {
                "groups": ["tumor", "normal"],
                "min_samples_per_group": 10
            },
            "dependencies": []
        },
        {
            "step_id": "step_2",
            "agent_type": "statistical_analysis",
            "action": "perform differential expression analysis",
            "parameters": {
                "method": "DESeq2",
                "fdr_cutoff": 0.05,
                "fold_change_cutoff": 1.0
            },
            "dependencies": ["step_1"]
        },
        {
            "step_id": "step_3",
            "agent_type": "statistical_analysis",
            "action": "perform pathway enrichment on DE genes",
            "parameters": {
                "databases": ["KEGG", "Reactome", "GO"],
                "fdr_cutoff": 0.05
            },
            "dependencies": ["step_2"]
        },
        {
            "step_id": "step_4",
            "agent_type": "visualization",
            "action": "create DE visualizations",
            "parameters": {
                "plot_types": ["volcano", "ma_plot", "heatmap"]
            },
            "dependencies": ["step_2", "step_3"]
        }
    ],
    "expected_duration": "15-20 minutes",
    "outputs": [
        "List of differentially expressed genes",
        "Enriched pathways",
        "Volcano plots and heatmaps"
    ]
}

biomarker_discovery_workflow = {
    "name": "Biomarker Discovery Pipeline",
    "description": "Comprehensive pipeline to discover and validate prognostic biomarkers",
    "steps": [
        {
            "step_id": "step_1",
            "agent_type": "data_curation",
            "action": "find discovery and validation cohorts",
            "parameters": {
                "discovery_size": 500,
                "validation_size": 300,
                "required_data": ["expression", "clinical", "survival"]
            },
            "dependencies": []
        },
        {
            "step_id": "step_2",
            "agent_type": "statistical_analysis",
            "action": "identify differentially expressed genes in discovery",
            "parameters": {
                "comparison": "tumor_vs_normal",
                "fdr_cutoff": 0.01
            },
            "dependencies": ["step_1"]
        },
        {
            "step_id": "step_3",
            "agent_type": "statistical_analysis",
            "action": "test survival associations for candidate genes",
            "parameters": {
                "method": "cox_regression",
                "p_cutoff": 0.05
            },
            "dependencies": ["step_2"]
        },
        {
            "step_id": "step_4",
            "agent_type": "statistical_analysis",
            "action": "validate biomarkers in independent cohort",
            "parameters": {
                "validation_method": "cox_regression"
            },
            "dependencies": ["step_3"]
        },
        {
            "step_id": "step_5",
            "agent_type": "visualization",
            "action": "create biomarker summary visualizations",
            "parameters": {
                "plot_types": ["survival_curves", "forest_plot", "heatmap"]
            },
            "dependencies": ["step_4"]
        },
        {
            "step_id": "step_6",
            "agent_type": "literature_mining",
            "action": "check literature for known vs novel biomarkers",
            "parameters": {
                "validation_threshold": 5
            },
            "dependencies": ["step_4"]
        }
    ],
    "expected_duration": "30-45 minutes",
    "outputs": [
        "Validated prognostic biomarkers",
        "Survival curves for each biomarker",
        "Literature support assessment"
    ]
}

multi_omics_integration_workflow = {
    "name": "Multi-Omics Integration",
    "description": "Integrate transcriptomics and proteomics data",
    "steps": [
        {
            "step_id": "step_1",
            "agent_type": "data_curation",
            "action": "find datasets with both RNA-seq and proteomics",
            "parameters": {
                "data_types": ["rna_seq", "proteomics"],
                "matched_samples": True
            },
            "dependencies": []
        },
        {
            "step_id": "step_2",
            "agent_type": "statistical_analysis",
            "action": "correlate mRNA and protein levels",
            "parameters": {
                "method": "spearman",
                "correction": "fdr"
            },
            "dependencies": ["step_1"]
        },
        {
            "step_id": "step_3",
            "agent_type": "statistical_analysis",
            "action": "identify discordant genes",
            "parameters": {
                "correlation_cutoff": 0.3
            },
            "dependencies": ["step_2"]
        },
        {
            "step_id": "step_4",
            "agent_type": "visualization",
            "action": "create multi-omics visualizations",
            "parameters": {
                "plot_types": ["scatter", "circos", "integrative_heatmap"]
            },
            "dependencies": ["step_2", "step_3"]
        }
    ],
    "expected_duration": "20-30 minutes",
    "outputs": [
        "mRNA-protein correlation results",
        "List of post-transcriptionally regulated genes",
        "Integrated visualizations"
    ]
}

# Export all workflows
EXAMPLE_WORKFLOWS = {
    "correlation": correlation_workflow,
    "survival": survival_workflow,
    "differential_expression": differential_expression_workflow,
    "biomarker_discovery": biomarker_discovery_workflow,
    "multi_omics": multi_omics_integration_workflow
}


def get_workflow(workflow_name: str) -> dict:
    """Get a workflow definition by name"""
    return EXAMPLE_WORKFLOWS.get(workflow_name)


def list_workflows() -> list:
    """List all available workflow templates"""
    return [
        {
            "id": key,
            "name": workflow["name"],
            "description": workflow["description"],
            "num_steps": len(workflow["steps"]),
            "duration": workflow["expected_duration"]
        }
        for key, workflow in EXAMPLE_WORKFLOWS.items()
    ]
