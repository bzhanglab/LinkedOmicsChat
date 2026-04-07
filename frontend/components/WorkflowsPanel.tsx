"use client"

import { useState, useEffect, useRef } from "react"
import { Play, Plus, Workflow as WorkflowIcon, Loader2, RefreshCw, X, ChevronDown, ChevronUp, FileText } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Input } from "@/components/ui/input"
import { workflowsAPI } from "@/lib/api"

interface Workflow {
    id: string
    name: string
    description: string
    steps: Array<{
        step_id: string
        status: string
        action: string
    }>
    status: string
    created_at?: string
}

interface WorkflowResults {
    workflow_id: string
    workflow_name: string
    status: string
    summary: string
    completed_at?: string
    steps: Array<{
        step_id: string
        agent_type: string
        action: string
        status: string
        result: any
    }>
}

export function WorkflowsPanel() {
    const [workflows, setWorkflows] = useState<Workflow[]>([])
    const [isLoading, setIsLoading] = useState(true)
    const [executingWorkflows, setExecutingWorkflows] = useState<Set<string>>(new Set())
    const [isSeeding, setIsSeeding] = useState(false)
    const [showParamDialog, setShowParamDialog] = useState<string | null>(null)
    const [workflowParams, setWorkflowParams] = useState<Record<string, string>>({
        gene_name: "",
        cancer_type: "",
        target_gene: ""
    })
    const [workflowResults, setWorkflowResults] = useState<Record<string, WorkflowResults>>({})
    const [expandedResults, setExpandedResults] = useState<Set<string>>(new Set())
    const pollingIntervals = useRef<Record<string, NodeJS.Timeout>>({})

    useEffect(() => {
        loadWorkflowsAndAutoSeed()
    }, [])

    const loadWorkflowsAndAutoSeed = async () => {
        try {
            setIsLoading(true)
            const data = await workflowsAPI.list()

            // Auto-load examples if no workflows exist
            if (!data || data.length === 0) {
                console.log("📋 No workflows found, auto-loading examples...")
                await handleSeedExamples()
                return
            }

            setWorkflows(data)

            // Load results for any completed workflows
            if (data && data.length > 0) {
                await loadResultsForCompletedWorkflows(data)
            }
        } catch (error) {
            console.error("Error loading workflows:", error)
        } finally {
            setIsLoading(false)
        }
    }

    const loadWorkflows = async (silent = false) => {
        try {
            if (!silent) {
                setIsLoading(true)
            }
            const data = await workflowsAPI.list()
            setWorkflows(data || [])

            // Load results for any completed workflows
            if (data && data.length > 0) {
                await loadResultsForCompletedWorkflows(data)
            }

            return data || []  // Return the data so it can be used immediately
        } catch (error) {
            console.error("Error loading workflows:", error)
            return []
        } finally {
            if (!silent) {
                setIsLoading(false)
            }
        }
    }

    const loadResultsForCompletedWorkflows = async (workflows: Workflow[]) => {
        // Fetch results for workflows that are completed, failed, or partially_completed
        const completedWorkflows = workflows.filter(w =>
            w.status === "completed" ||
            w.status === "failed" ||
            w.status === "partially_completed"
        )

        // Fetch results for each completed workflow
        const resultsPromises = completedWorkflows.map(async (workflow) => {
            try {
                const results = await workflowsAPI.getResults(workflow.id)
                return { workflowId: workflow.id, results }
            } catch (error) {
                console.error(`Error loading results for workflow ${workflow.id}:`, error)
                return null
            }
        })

        const resultsArray = await Promise.all(resultsPromises)

        // Update workflowResults state with all fetched results
        const newResults: Record<string, WorkflowResults> = {}
        resultsArray.forEach(item => {
            if (item && item.results) {
                newResults[item.workflowId] = item.results
            }
        })

        if (Object.keys(newResults).length > 0) {
            setWorkflowResults(prev => ({ ...prev, ...newResults }))
        }
    }

    // Update a single workflow's status without reloading all workflows
    const updateWorkflowStatus = (workflowId: string, status: any) => {
        setWorkflows(prev => prev.map(wf =>
            wf.id === workflowId
                ? {
                    ...wf,
                    status: status.status,
                    steps: status.steps?.map((s: any) => ({
                        step_id: s.step_id,
                        status: s.status,
                        action: s.action
                    })) || wf.steps
                }
                : wf
        ))
    }

    const handleSeedExamples = async () => {
        try {
            setIsSeeding(true)
            console.log("🌱 Seeding example workflows...")
            const result = await workflowsAPI.seedExamples()
            console.log("✅ Seeded workflows result:", result)
            await loadWorkflows()
            console.log("✅ Workflows loaded, count:", workflows.length)
        } catch (error) {
            console.error("❌ Error seeding examples:", error)
            alert(`Failed to load example workflows: ${error instanceof Error ? error.message : String(error)}`)
        } finally {
            setIsSeeding(false)
        }
    }

    const handleExecute = async (workflowId: string, parameters?: Record<string, any>) => {
        if (!workflowId) {
            console.error("❌ No workflow ID provided")
            alert("Error: No workflow selected. Please try again.")
            return
        }

        // Always reload workflows from backend first (they're in-memory and may be cleared on restart)
        console.log("🔄 Reloading workflows from backend...")
        const reloadedWorkflows = await loadWorkflows(false)

        // Check if workflow exists in backend
        const workflow = reloadedWorkflows.find((w: Workflow) => w.id === workflowId)
        if (!workflow) {
            console.error("❌ Workflow not found in backend:", workflowId)
            console.log("Available workflows:", reloadedWorkflows.map((w: Workflow) => ({ id: w.id, name: w.name })))
            alert(`Workflow not found. Please:\n1. Click 'Load Example Workflows' first\n2. Wait for workflows to appear\n3. Then click 'Run' on a workflow\n\nNote: If you restarted the backend, workflows are cleared and need to be reloaded.`)
            return
        }
        console.log("✅ Found workflow:", workflow.name)

        try {
            setShowParamDialog(null) // Close dialog

            // Log what we're sending
            const paramsToSend = parameters || {}
            console.log("🚀 Executing workflow:", workflowId)
            console.log("📋 Parameters being sent:", paramsToSend)

            if (Object.keys(paramsToSend).length === 0) {
                console.warn("⚠️ No parameters provided - workflow will use default/placeholder values")
            }

            setExecutingWorkflows(prev => new Set(prev).add(workflowId))

            // Execute workflow with user parameters
            console.log("📡 Calling workflowsAPI.execute...")
            const response = await workflowsAPI.execute(workflowId, paramsToSend)
            console.log("✅ Workflow execution response:", response)

            // Poll for status updates (without flickering)
            const pollInterval = setInterval(async () => {
                try {
                    const status = await workflowsAPI.getStatus(workflowId)
                    // Update status in place instead of reloading all workflows
                    updateWorkflowStatus(workflowId, status)

                    // Stop polling if workflow is done
                    if (["completed", "failed", "partially_completed"].includes(status.status)) {
                        clearInterval(pollInterval)
                        delete pollingIntervals.current[workflowId]
                        setExecutingWorkflows(prev => {
                            const newSet = new Set(prev)
                            newSet.delete(workflowId)
                            return newSet
                        })

                        // Fetch results when workflow completes
                        try {
                            const results = await workflowsAPI.getResults(workflowId)
                            setWorkflowResults(prev => ({
                                ...prev,
                                [workflowId]: results
                            }))
                        } catch (error) {
                            console.error("Error fetching workflow results:", error)
                        }
                    }
                } catch (error) {
                    console.error("Error polling workflow status:", error)
                    clearInterval(pollInterval)
                    delete pollingIntervals.current[workflowId]
                    setExecutingWorkflows(prev => {
                        const newSet = new Set(prev)
                        newSet.delete(workflowId)
                        return newSet
                    })
                }
            }, 3000) // Poll every 3 seconds (reduced frequency to reduce flicker)

            pollingIntervals.current[workflowId] = pollInterval

            // Stop polling after 5 minutes max
            setTimeout(() => {
                if (pollingIntervals.current[workflowId]) {
                    clearInterval(pollingIntervals.current[workflowId])
                    delete pollingIntervals.current[workflowId]
                }
                setExecutingWorkflows(prev => {
                    const newSet = new Set(prev)
                    newSet.delete(workflowId)
                    return newSet
                })
            }, 300000)

        } catch (error: any) {
            console.error("❌ Error executing workflow:", error)
            console.error("Error details:", error instanceof Error ? error.message : String(error))
            if (error instanceof Error && error.stack) {
                console.error("Stack trace:", error.stack)
            }
            setExecutingWorkflows(prev => {
                const newSet = new Set(prev)
                newSet.delete(workflowId)
                return newSet
            })
            if (pollingIntervals.current[workflowId]) {
                clearInterval(pollingIntervals.current[workflowId])
                delete pollingIntervals.current[workflowId]
            }

            // Better error message
            let errorMessage = "Failed to execute workflow"
            if (error?.response?.status === 404) {
                errorMessage = "Workflow not found. Please make sure you've loaded example workflows first."
            } else if (error?.response?.status === 400) {
                errorMessage = error?.response?.data?.detail || "Invalid request. Please check your parameters."
            } else if (error?.message) {
                errorMessage = `Failed to execute workflow: ${error.message}`
            }

            // Show error to user
            alert(errorMessage)
        }
    }

    // Cleanup polling intervals on unmount
    useEffect(() => {
        return () => {
            Object.values(pollingIntervals.current).forEach(interval => clearInterval(interval))
        }
    }, [])

    const toggleResults = (workflowId: string) => {
        setExpandedResults(prev => {
            const newSet = new Set(prev)
            if (newSet.has(workflowId)) {
                newSet.delete(workflowId)
            } else {
                newSet.add(workflowId)
            }
            return newSet
        })
    }

    const getStatusColor = (status: string) => {
        switch (status) {
            case "completed":
                return "bg-green-500/10 text-green-500"
            case "running":
                return "bg-teal-500/10 text-teal-500"
            case "failed":
                return "bg-red-500/10 text-red-500"
            case "partially_completed":
                return "bg-yellow-500/10 text-yellow-500"
            default:
                return "bg-gray-500/10 text-gray-500"
        }
    }

    return (
        <div className="h-full flex flex-col bg-background">
            {/* Header */}
            <div className="border-b border-border p-6 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <WorkflowIcon className="h-5 w-5" />
                    <h2 className="text-lg font-semibold">Workflows</h2>
                </div>
            </div>

            {/* Workflows List */}
            <ScrollArea className="flex-1">
                <div className="p-6 space-y-4">
                    {isLoading ? (
                        <div className="flex items-center justify-center h-64">
                            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                        </div>
                    ) : workflows.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-64 text-center">
                            <WorkflowIcon className="h-12 w-12 text-muted-foreground mb-4" />
                            <h3 className="text-lg font-medium">No workflows yet</h3>
                            <p className="text-sm text-muted-foreground mt-2 mb-4">
                                Load example workflows or create your first automated analysis workflow
                            </p>
                            <Button onClick={handleSeedExamples} disabled={isSeeding}>
                                {isSeeding ? (
                                    <>
                                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                        Seeding...
                                    </>
                                ) : (
                                    <>
                                        <Plus className="h-4 w-4 mr-2" />
                                        Load Example Workflows
                                    </>
                                )}
                            </Button>
                        </div>
                    ) : (
                        workflows.map((workflow) => {
                            const isExecuting = executingWorkflows.has(workflow.id)
                            const isRunning = workflow.status === "running" || isExecuting

                            return (
                                <Card key={workflow.id} className="hover:shadow-lg transition-shadow">
                                    <CardHeader>
                                        <div className="flex items-start justify-between">
                                            <div className="flex items-start gap-3">
                                                <div className="p-2 bg-primary/10 rounded-lg">
                                                    <WorkflowIcon className="h-5 w-5 text-primary" />
                                                </div>
                                                <div>
                                                    <CardTitle className="text-lg">{workflow.name}</CardTitle>
                                                    <CardDescription className="mt-1">
                                                        {workflow.description}
                                                    </CardDescription>
                                                </div>
                                            </div>
                                            <Button
                                                size="sm"
                                                onClick={() => {
                                                    // Reset parameters when opening dialog
                                                    setWorkflowParams({
                                                        gene_name: "",
                                                        cancer_type: "",
                                                        target_gene: ""
                                                    })
                                                    setShowParamDialog(workflow.id)
                                                }}
                                                disabled={isRunning || workflow.status === "running"}
                                            >
                                                {isRunning ? (
                                                    <>
                                                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                                        Running...
                                                    </>
                                                ) : (
                                                    <>
                                                        <Play className="h-4 w-4 mr-2" />
                                                        Run
                                                    </>
                                                )}
                                            </Button>
                                        </div>
                                    </CardHeader>
                                    <CardContent>
                                        <div className="flex items-center gap-4 text-sm">
                                            <span className="text-muted-foreground">
                                                {workflow.steps?.length || 0} steps
                                            </span>
                                            <span className={`px-2 py-1 rounded-md text-xs ${getStatusColor(workflow.status)}`}>
                                                {workflow.status}
                                            </span>
                                        </div>
                                        {workflow.steps && workflow.steps.length > 0 && (
                                            <div className="mt-3 pt-3 border-t border-border">
                                                <p className="text-xs text-muted-foreground mb-2">Steps:</p>
                                                <div className="space-y-1">
                                                    {workflow.steps.map((step, idx) => (
                                                        <div key={idx} className="flex items-center gap-2 text-xs">
                                                            <span className={`w-2 h-2 rounded-full ${step.status === "completed" ? "bg-green-500" :
                                                                step.status === "running" ? "bg-teal-500 animate-pulse" :
                                                                    step.status === "failed" ? "bg-red-500" :
                                                                        "bg-gray-300"
                                                                }`} />
                                                            <span className="text-muted-foreground">
                                                                {step.step_id}: {step.action}
                                                            </span>
                                                            {step.status && (
                                                                <span className={`text-xs ${getStatusColor(step.status)}`}>
                                                                    {step.status}
                                                                </span>
                                                            )}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Results Section */}
                                        {workflowResults[workflow.id] && (
                                            <div className="mt-4 pt-4 border-t border-border">
                                                <button
                                                    onClick={() => toggleResults(workflow.id)}
                                                    className="flex items-center justify-between w-full text-left"
                                                >
                                                    <div className="flex items-center gap-2">
                                                        <FileText className="h-4 w-4 text-primary" />
                                                        <span className="text-sm font-medium">Execution Results</span>
                                                        {workflowResults[workflow.id].status === "completed" && (
                                                            <span className="text-xs px-2 py-0.5 rounded bg-green-500/10 text-green-500">
                                                                {workflowResults[workflow.id].status}
                                                            </span>
                                                        )}
                                                    </div>
                                                    {expandedResults.has(workflow.id) ? (
                                                        <ChevronUp className="h-4 w-4" />
                                                    ) : (
                                                        <ChevronDown className="h-4 w-4" />
                                                    )}
                                                </button>

                                                {expandedResults.has(workflow.id) && (
                                                    <div className="mt-3 space-y-3">
                                                        {/* Summary */}
                                                        <div className="p-3 bg-muted rounded-md">
                                                            <p className="text-xs whitespace-pre-wrap">
                                                                {workflowResults[workflow.id].summary}
                                                            </p>
                                                        </div>

                                                        {/* Step Results */}
                                                        <div className="space-y-2">
                                                            {workflowResults[workflow.id].steps.map((step, idx) => {
                                                                const result = step.result || {}
                                                                const data = result.data || {}
                                                                const isMock = data.is_mock || result.is_mock || false

                                                                return (
                                                                    <details key={idx} className="border rounded-md p-2">
                                                                        <summary className="cursor-pointer text-sm font-medium flex items-center justify-between">
                                                                            <div className="flex items-center gap-2">
                                                                                <span>
                                                                                    {step.step_id}: {step.action}
                                                                                </span>
                                                                                {isMock && (
                                                                                    <span className="text-xs px-2 py-0.5 rounded bg-yellow-500/10 text-yellow-600 border border-yellow-500/20">
                                                                                        Mock Data
                                                                                    </span>
                                                                                )}
                                                                            </div>
                                                                            <span className={`text-xs px-2 py-0.5 rounded ${step.status === "completed" ? "bg-green-500/10 text-green-500" :
                                                                                step.status === "failed" ? "bg-red-500/10 text-red-500" :
                                                                                    "bg-gray-500/10 text-gray-500"
                                                                                }`}>
                                                                                {step.status}
                                                                            </span>
                                                                        </summary>
                                                                        <div className="mt-2 space-y-3">
                                                                            {/* Display plots if available */}
                                                                            {data.visualizations && data.visualizations.length > 0 && (
                                                                                <div className="space-y-3">
                                                                                    {data.visualizations.map((viz: any, vizIdx: number) => {
                                                                                        if (viz.plot_image && viz.plot_image.data) {
                                                                                            return (
                                                                                                <div key={vizIdx} className="border rounded-lg p-3 bg-background">
                                                                                                    <h5 className="text-sm font-semibold mb-2">{viz.plot_image.title || viz.title || "Visualization"}</h5>
                                                                                                    <img
                                                                                                        src={viz.plot_image.data}
                                                                                                        alt={viz.plot_image.title || "Plot"}
                                                                                                        className="w-full rounded border"
                                                                                                    />
                                                                                                </div>
                                                                                            )
                                                                                        }
                                                                                        return null
                                                                                    })}
                                                                                </div>
                                                                            )}

                                                                            {/* Format results based on agent type */}
                                                                            {step.agent_type === "statistical_analysis" && data.results && (
                                                                                <div className="p-3 bg-muted rounded text-sm">
                                                                                    <h6 className="font-semibold mb-2">Analysis Results</h6>
                                                                                    <div className="space-y-1 text-xs">
                                                                                        <p><strong>Method:</strong> {data.results.method || "N/A"}</p>
                                                                                        <p><strong>Genes Tested:</strong> {data.results.n_genes_tested || "N/A"}</p>
                                                                                        {data.results.significant_genes !== undefined && (
                                                                                            <p><strong>Significant Genes:</strong> {data.results.significant_genes}</p>
                                                                                        )}
                                                                                        {data.results.top_correlations && (
                                                                                            <div className="mt-2">
                                                                                                <p className="font-semibold mb-1">Top Correlations:</p>
                                                                                                <div className="max-h-40 overflow-y-auto">
                                                                                                    <table className="w-full text-xs">
                                                                                                        <thead>
                                                                                                            <tr className="border-b">
                                                                                                                <th className="text-left p-1">Gene</th>
                                                                                                                <th className="text-right p-1">Correlation</th>
                                                                                                                <th className="text-right p-1">p-value</th>
                                                                                                            </tr>
                                                                                                        </thead>
                                                                                                        <tbody>
                                                                                                            {data.results.top_correlations.slice(0, 10).map((corr: any, i: number) => (
                                                                                                                <tr key={i} className="border-b">
                                                                                                                    <td className="p-1">{corr.gene}</td>
                                                                                                                    <td className="text-right p-1">{corr.correlation.toFixed(3)}</td>
                                                                                                                    <td className="text-right p-1">{corr.p_value.toFixed(4)}</td>
                                                                                                                </tr>
                                                                                                            ))}
                                                                                                        </tbody>
                                                                                                    </table>
                                                                                                </div>
                                                                                            </div>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                            )}

                                                                            {step.agent_type === "data_curation" && data.datasets && (
                                                                                <div className="p-3 bg-muted rounded text-sm">
                                                                                    <h6 className="font-semibold mb-2">Datasets Found</h6>
                                                                                    <p className="text-xs">{data.message || "No datasets found"}</p>
                                                                                    {data.datasets.length > 0 && (
                                                                                        <div className="mt-2 space-y-1">
                                                                                            {data.datasets.slice(0, 5).map((ds: any, i: number) => (
                                                                                                <div key={i} className="text-xs p-2 bg-background rounded">
                                                                                                    <p className="font-medium">{ds.name}</p>
                                                                                                    <p className="text-muted-foreground">{ds.sample_count} samples</p>
                                                                                                </div>
                                                                                            ))}
                                                                                        </div>
                                                                                    )}
                                                                                </div>
                                                                            )}

                                                                            {step.agent_type === "literature_mining" && data.papers && (
                                                                                <div className="p-3 bg-muted rounded text-sm">
                                                                                    <h6 className="font-semibold mb-2">Papers Found ({data.papers.length})</h6>
                                                                                    <div className="space-y-2 max-h-60 overflow-y-auto">
                                                                                        {data.papers.slice(0, 5).map((paper: any, i: number) => (
                                                                                            <div key={i} className="p-2 bg-background rounded text-xs">
                                                                                                <p className="font-medium">{paper.title}</p>
                                                                                                {paper.link && (
                                                                                                    <a href={paper.link} target="_blank" rel="noopener noreferrer" className="text-teal-500 hover:underline">
                                                                                                        View Paper →
                                                                                                    </a>
                                                                                                )}
                                                                                            </div>
                                                                                        ))}
                                                                                    </div>
                                                                                </div>
                                                                            )}

                                                                            {/* Fallback to JSON for unknown formats */}
                                                                            {!data.visualizations && !data.results && !data.datasets && !data.papers && (
                                                                                <div className="p-2 bg-muted rounded text-xs">
                                                                                    <pre className="whitespace-pre-wrap overflow-x-auto">
                                                                                        {JSON.stringify(step.result, null, 2)}
                                                                                    </pre>
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                    </details>
                                                                )
                                                            })}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </CardContent>
                                </Card>
                            )
                        })
                    )}
                </div>
            </ScrollArea>

            {/* Parameter Input Dialog */}
            {showParamDialog && (
                <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center z-50">
                    <Card className="w-full max-w-md mx-4">
                        <CardHeader>
                            <div className="flex items-center justify-between">
                                <CardTitle>Workflow Parameters</CardTitle>
                                <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => setShowParamDialog(null)}
                                >
                                    <X className="h-4 w-4" />
                                </Button>
                            </div>
                            <CardDescription>
                                Provide parameters for the workflow execution. At least a gene name is required.
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div>
                                <label className="text-sm font-medium mb-2 block">
                                    Target Gene (e.g., BRCA1, TP53)
                                </label>
                                <Input
                                    placeholder="Enter gene name"
                                    value={workflowParams.gene_name || workflowParams.target_gene || ""}
                                    onChange={(e) => setWorkflowParams({
                                        ...workflowParams,
                                        gene_name: e.target.value,
                                        target_gene: e.target.value
                                    })}
                                />
                            </div>
                            <div>
                                <label className="text-sm font-medium mb-2 block">
                                    Cancer Type (e.g., breast cancer, lung cancer)
                                </label>
                                <Input
                                    placeholder="Enter cancer type"
                                    value={workflowParams.cancer_type || ""}
                                    onChange={(e) => setWorkflowParams({
                                        ...workflowParams,
                                        cancer_type: e.target.value
                                    })}
                                />
                            </div>
                            <div className="flex gap-2 pt-4">
                                <Button
                                    className="flex-1"
                                    disabled={(!workflowParams.gene_name?.trim() && !workflowParams.target_gene?.trim()) || !showParamDialog}
                                    onClick={async () => {
                                        console.log("🔘 Run Workflow button clicked")
                                        console.log("🔘 Current params:", workflowParams)
                                        console.log("🔘 showParamDialog:", showParamDialog)
                                        if (!showParamDialog) {
                                            console.error("❌ No workflow ID in dialog state")
                                            return
                                        }

                                        const params: Record<string, any> = {}
                                        const geneName = (workflowParams.gene_name || workflowParams.target_gene || "").trim()
                                        const cancerType = (workflowParams.cancer_type || "").trim()

                                        if (geneName) {
                                            params.gene_name = geneName
                                            params.target_gene = geneName
                                        }
                                        if (cancerType) {
                                            params.cancer_type = cancerType
                                        }

                                        // Log what parameters are being sent
                                        console.log("🔘 Button clicked - Executing workflow with parameters:", params)
                                        console.log("🔘 Workflow ID:", showParamDialog)

                                        await handleExecute(showParamDialog, params)
                                    }}
                                >
                                    <Play className="h-4 w-4 mr-2" />
                                    Run Workflow
                                </Button>
                                <Button
                                    variant="outline"
                                    onClick={() => setShowParamDialog(null)}
                                >
                                    Cancel
                                </Button>
                            </div>
                        </CardContent>
                    </Card>
                </div>
            )}
        </div>
    )
}
