"use client"

import { useState, useRef, useEffect } from "react"
import { Send, Loader2, Sparkles, Copy, Check } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Card, CardContent } from "@/components/ui/card"
import { chatAPI, type ChatMessage, type Paper, type AnalysisResult, API_URL } from "@/lib/api"
import axios from "axios"
import { cn } from "@/lib/utils"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import rehypeHighlight from "rehype-highlight"
import "highlight.js/styles/github-dark.css"

interface ChatInterfaceProps {
    sessionId: string | null
    onSessionChange: (sessionId: string) => void
}

export function ChatInterface({ sessionId, onSessionChange }: ChatInterfaceProps) {
    const [messages, setMessages] = useState<ChatMessage[]>([])
    const [input, setInput] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
    const scrollRef = useRef<HTMLDivElement>(null)
    const [suggestions] = useState([
        "Find genes correlated with TP53 in breast cancer",
        "Perform survival analysis for EGFR in lung cancer",
        "Show me TCGA datasets with proteomics data",
        "What pathways are enriched in my gene list?",
    ])

    const handleCopy = async (content: string, index: number) => {
        try {
            await navigator.clipboard.writeText(content)
            setCopiedIndex(index)
            setTimeout(() => setCopiedIndex(null), 2000)
        } catch (error) {
            console.error("Failed to copy:", error)
        }
    }

    // Initialize welcome message on client side only to avoid hydration mismatch
    useEffect(() => {
        setMessages([
            {
                role: "assistant",
                content: "Hello! I'm cpgAgent, your AI research assistant for multi-omics analysis. Ask me anything about gene expression, correlations, survival analysis, or help finding relevant datasets.",
                timestamp: new Date(),
            },
        ])
    }, [])

    // Reset messages when session changes
    useEffect(() => {
        if (!sessionId) {
            // New chat - show welcome message and create session
            setMessages([
                {
                    role: "assistant",
                    content: "Hello! I'm cpgAgent, your AI research assistant for multi-omics analysis. Ask me anything about gene expression, correlations, survival analysis, or help finding relevant datasets.",
                    timestamp: new Date(),
                },
            ])
            // Create a new session immediately so it appears in sidebar
            createNewSession()
        } else {
            // Load session history
            loadSessionHistory(sessionId)
        }
    }, [sessionId])

    const createNewSession = async () => {
        try {
            // Make a dummy request to create the session
            // The backend will create a session when we send our first real message
            // For now, we'll let it happen naturally with the first message
        } catch (error) {
            console.error("Failed to create session:", error)
        }
    }

    const loadSessionHistory = async (sid: string) => {
        try {
            const response = await fetch(`${API_URL}/api/v1/chat/sessions/${sid}`)
            if (response.ok) {
                const data = await response.json()
                const history = data.history || []
                const loadedMessages: ChatMessage[] = []
                
                for (const item of history) {
                    loadedMessages.push({
                        role: "user",
                        content: item.query,
                        timestamp: new Date(item.timestamp * 1000),
                    })
                    
                    // Extract papers from response (could be in papers or metadata.papers)
                    const papers = item.response?.papers || item.response?.metadata?.papers || []
                    
                    // Extract analyses from response
                    const analyses = (item.response?.analyses || []) as AnalysisResult[]
                    
                    loadedMessages.push({
                        role: "assistant",
                        content: item.response?.summary || item.response?.message || "",
                        timestamp: new Date(item.timestamp * 1000),
                        papers: papers.length > 0 ? papers : undefined,
                        analyses: analyses.length > 0 ? analyses : undefined,
                    })
                }
                
                setMessages(loadedMessages.length > 0 ? loadedMessages : [
                    {
                        role: "assistant",
                        content: "Hello! I'm cpgAgent, your AI research assistant for multi-omics analysis.",
                        timestamp: new Date(),
                    },
                ])
            }
        } catch (error) {
            console.error("Failed to load session history:", error)
        }
    }

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
    }, [messages])

    const handleSend = async () => {
        // Workaround for browser automation: check DOM value if React state is empty
        let messageText = input.trim()
        if (!messageText) {
            const inputElement = document.querySelector('input[placeholder*="genes, datasets"]') as HTMLInputElement
            if (inputElement && inputElement.value.trim()) {
                messageText = inputElement.value.trim()
                setInput(messageText) // Update React state
            }
        }
        
        if (!messageText || isLoading) {
            return
        }

        const userMessage: ChatMessage = {
            role: "user",
            content: messageText,
            timestamp: new Date(),
        }

        setMessages((prev) => [...prev, userMessage])
        setInput("")
        setIsLoading(true)

        try {
            const response = await chatAPI.sendMessage({
                message: messageText,
                session_id: sessionId || undefined,
            })

            if (response.session_id && !sessionId) {
                onSessionChange(response.session_id)
            }

            // Extract papers from metadata
            const papers = response.metadata?.papers as Paper[] || []
            
            // Extract analyses from response - ensure proper typing
            const analyses = (response.analyses || []) as AnalysisResult[]
            
            // Debug logging
            console.log("Received response:", {
                messageLength: response.message?.length || 0,
                analysesCount: analyses.length,
                hasAnalyses: analyses.length > 0
            })
            
            if (analyses.length > 0) {
                const firstAnalysis = analyses[0]
                console.log("First analysis details:", {
                    type: firstAnalysis.analysis_type,
                    has_upregulated: !!firstAnalysis.top_upregulated,
                    upregulated_count: firstAnalysis.top_upregulated?.length || 0,
                    has_downregulated: !!firstAnalysis.top_downregulated,
                    downregulated_count: firstAnalysis.top_downregulated?.length || 0,
                    total_results: firstAnalysis.total_results,
                    significant_results: firstAnalysis.significant_results
                })
                
                // Log first upregulated gene if available
                if (firstAnalysis.top_upregulated && firstAnalysis.top_upregulated.length > 0) {
                    console.log("First upregulated gene:", firstAnalysis.top_upregulated[0])
                }
            }

            const assistantMessage: ChatMessage = {
                role: "assistant",
                content: response.message || "Analysis completed. See results below.",
                timestamp: new Date(),
                papers: papers.length > 0 ? papers : undefined,
                analyses: analyses.length > 0 ? analyses : undefined,
            }

            setMessages((prev) => [...prev, assistantMessage])
        } catch (error) {
            console.error("Error sending message:", error)
            
            // Determine the error message based on error type
            let errorContent = "I apologize, but I encountered an error processing your request."
            
            if (axios.isAxiosError(error)) {
                if (error.code === 'ECONNREFUSED' || error.code === 'ERR_NETWORK' || !error.response) {
                    errorContent = "Unable to connect to the backend server. Please make sure the backend is running on " + API_URL + ". You can start it by running `./start_backend.sh` or `python backend/main.py`."
                } else if (error.response) {
                    // Server responded with error status
                    const status = error.response.status
                    const detail = error.response.data?.detail || error.response.data?.error || error.message
                    errorContent = `Server error (${status}): ${detail}. Please try again.`
                } else if (error.request) {
                    // Request was made but no response received
                    errorContent = "The request was sent but no response was received. The backend may be taking too long to respond or may be unavailable."
                } else {
                    errorContent = `Request error: ${error.message}. Please try again.`
                }
            } else if (error instanceof Error) {
                errorContent = `Error: ${error.message}. Please try again.`
            } else {
                errorContent = `An unexpected error occurred: ${String(error)}. Please try again.`
            }
            
            const errorMessage: ChatMessage = {
                role: "assistant",
                content: errorContent,
                timestamp: new Date(),
            }
            setMessages((prev) => [...prev, errorMessage])
        } finally {
            setIsLoading(false)
        }
    }

    const handleSuggestionClick = (suggestion: string) => {
        setInput(suggestion)
    }

    return (
        <div className="h-full flex flex-col bg-background">
            {/* Header */}
            <div className="border-b border-border p-6">
                <h2 className="text-2xl font-semibold">Multi-Omics Analysis</h2>
                <p className="text-sm text-muted-foreground mt-1">
                    Ask questions in natural language and let AI agents handle the analysis
                </p>
            </div>

            {/* Messages */}
            <ScrollArea className="flex-1 p-6">
                <div ref={scrollRef} className="space-y-4 max-w-4xl mx-auto">
                    {messages.map((message, index) => (
                        <div
                            key={index}
                            className={cn(
                                "flex gap-3",
                                message.role === "user" ? "justify-end" : "justify-start"
                            )}
                        >
                            {message.role === "assistant" && (
                                <div className="flex-shrink-0">
                                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center">
                                        <Sparkles className="w-4 h-4 text-white" />
                                    </div>
                                </div>
                            )}
                            <Card
                                className={cn(
                                    "max-w-[80%] relative group",
                                    message.role === "user"
                                        ? "bg-primary text-primary-foreground"
                                        : "bg-card"
                                )}
                            >
                                <CardContent className="p-4">
                                    {message.role === "assistant" ? (
                                        <div className="prose prose-sm dark:prose-invert max-w-none">
                                            <ReactMarkdown
                                                remarkPlugins={[remarkGfm]}
                                                rehypePlugins={[rehypeHighlight]}
                                                components={{
                                                    code: ({ node, className, children, ...props }: any) => {
                                                        const match = /language-(\w+)/.exec(className || '')
                                                        const isInline = !match
                                                        
                                                        if (isInline) {
                                                            return (
                                                                <code className="bg-muted px-1 py-0.5 rounded text-sm font-mono" {...props}>
                                                                    {children}
                                                                </code>
                                                            )
                                                        }
                                                        return (
                                                            <code className={className} {...props}>
                                                                {children}
                                                            </code>
                                                        )
                                                    },
                                                }}
                                            >
                                                {message.content}
                                            </ReactMarkdown>
                                        </div>
                                    ) : (
                                        <p className="text-sm whitespace-pre-wrap">{message.content}</p>
                                    )}
                                    {message.timestamp && (
                                        <p className="text-xs opacity-70 mt-2">
                                            {message.timestamp.toLocaleTimeString()}
                                        </p>
                                    )}
                                    
                                                    {/* Display analysis results if available */}
                                    {message.analyses && message.analyses.length > 0 && (
                                        <div className="mt-4 pt-4 border-t border-border">
                                            <h4 className="text-sm font-semibold mb-3 flex items-center gap-2">
                                                <Sparkles className="w-4 h-4" />
                                                Analysis Results
                                            </h4>
                                            {message.analyses.map((analysis, idx) => (
                                                <div key={idx} className="mb-4 last:mb-0">
                                                    <div className="p-4 rounded-lg bg-muted/50 border border-border">
                                                        <div className="mb-3">
                                                            <h5 className="text-sm font-semibold mb-1">
                                                                {analysis.analysis_type === 'differential_expression' 
                                                                    ? 'Differential Expression Analysis'
                                                                    : analysis.analysis_type === 'pathway_enrichment'
                                                                    ? 'Pathway Enrichment Analysis'
                                                                    : analysis.data_source === 'CPTAC' && analysis.data_type === 'proteomics' 
                                                                    ? 'Protein Correlation Analysis' 
                                                                    : 'Gene Correlation Analysis'}
                                                            </h5>
                                                            <p className="text-xs text-muted-foreground">
                                                                {analysis.analysis_type === 'differential_expression' ? (
                                                                    <>
                                                                        Comparison: <span className="font-medium">{analysis.group1}</span> vs <span className="font-medium">{analysis.group2}</span> • 
                                                                        Cancer Type: <span className="font-medium">{analysis.cancer_type}</span> • 
                                                                        Dataset: <span className="font-medium">{analysis.data_source || 'TCGA'}</span>
                                                                    </>
                                                                ) : analysis.analysis_type === 'pathway_enrichment' ? (
                                                                    <>
                                                                        Genes analyzed: <span className="font-medium">{analysis.pathway_enrichment?.genes?.length || 'N/A'}</span> • 
                                                                        Gene set: <span className="font-medium">{(analysis.pathway_enrichment?.gene_set || '').replace(/_/g, ' ')}</span>
                                                                    </>
                                                                ) : (
                                                                    <>
                                                                        Target: <span className="font-medium">{analysis.target_gene}</span> • 
                                                                        Cancer Type: <span className="font-medium">{analysis.cancer_type}</span> • 
                                                                        Dataset: <span className="font-medium">{analysis.data_source || 'TCGA'}</span>
                                                                    </>
                                                                )}
                                                            </p>
                                                        </div>
                                                        
                                                        {analysis.analysis_type === 'pathway_enrichment' ? (
                                                            analysis.pathway_enrichment && analysis.pathway_enrichment.total_pathways !== undefined && (
                                                                <div className="mb-3 text-sm">
                                                                    <p>
                                                                        Found <span className="font-semibold">{analysis.pathway_enrichment.total_pathways}</span> enriched pathways
                                                                        {analysis.pathway_enrichment.top_pathways && (
                                                                            <> • Showing top <span className="font-semibold text-green-600 dark:text-green-400">{analysis.pathway_enrichment.top_pathways.length}</span> pathways</>
                                                                        )}
                                                                    </p>
                                                                </div>
                                                            )
                                                        ) : analysis.analysis_type === 'differential_expression' && analysis.total_results !== undefined ? (
                                                            <div className="mb-3 text-sm">
                                                                <p>
                                                                    Found <span className="font-semibold">{analysis.total_results}</span> genes tested between groups
                                                                    {analysis.group1_samples !== undefined && analysis.group2_samples !== undefined && (
                                                                        <> ({analysis.group1_samples} vs {analysis.group2_samples} samples)</>
                                                                    )}
                                                                    {analysis.significant_results !== undefined && (
                                                                        <> • <span className="font-semibold text-green-600 dark:text-green-400">{analysis.significant_results}</span> significantly different</>
                                                                    )}
                                                                </p>
                                                            </div>
                                                        ) : analysis.total_results !== undefined && (
                                                            <div className="mb-3 text-sm">
                                                                {analysis.analysis_type === 'differential_expression' ? (
                                                                    <p>
                                                                        Found <span className="font-semibold">{analysis.total_results}</span> genes tested between groups
                                                                        {analysis.group1_samples !== undefined && analysis.group2_samples !== undefined && (
                                                                            <> ({analysis.group1_samples} vs {analysis.group2_samples} samples)</>
                                                                        )}
                                                                        {analysis.significant_results !== undefined && (
                                                                            <> • <span className="font-semibold text-green-600 dark:text-green-400">{analysis.significant_results}</span> significantly different</>
                                                                        )}
                                                                    </p>
                                                                ) : (
                                                                    <p>
                                                                        Found <span className="font-semibold">{analysis.total_results}</span> {' '}
                                                                        {analysis.data_source === 'CPTAC' && analysis.data_type === 'proteomics' ? 'proteins' : 'genes'} 
                                                                        {' '}correlated
                                                                        {analysis.significant_results !== undefined && (
                                                                            <> • <span className="font-semibold text-green-600 dark:text-green-400">{analysis.significant_results}</span> statistically significant</>
                                                                        )}
                                                                    </p>
                                                                )}
                                                            </div>
                                                        )}
                                                        
                                                        {analysis.top_correlations && analysis.top_correlations.length > 0 && (
                                                            <div className="mb-3">
                                                                <p className="text-xs font-medium text-muted-foreground mb-2">Top Correlations:</p>
                                                                <div className="space-y-1">
                                                                    {analysis.top_correlations.slice(0, 10).map((corr: any, corrIdx: number) => (
                                                                        <div key={corrIdx} className="flex items-center justify-between text-xs p-2 rounded bg-background/50">
                                                                            <span className="font-medium">{corr.gene}</span>
                                                                            <div className="flex items-center gap-3 text-muted-foreground">
                                                                                <span>r = {corr.correlation.toFixed(3)}</span>
                                                                                <span>p = {corr.adjusted_p_value.toExponential(2)}</span>
                                                                                {corr.significant && (
                                                                                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-green-500/20 text-green-600 dark:text-green-400">
                                                                                        Significant
                                                                                    </span>
                                                                                )}
                                                                            </div>
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                            </div>
                                                        )}
                                                        
                                                        {analysis.analysis_type === 'differential_expression' && (
                                                            <>
                                                                {analysis.top_upregulated && analysis.top_upregulated.length > 0 && (
                                                                    <div className="mb-3">
                                                                        <p className="text-xs font-medium text-muted-foreground mb-2">
                                                                            Top Upregulated Genes (in {analysis.group1}):
                                                                        </p>
                                                                        <div className="space-y-1">
                                                                            {analysis.top_upregulated.slice(0, 10).map((gene: any, geneIdx: number) => (
                                                                                <div key={geneIdx} className="flex items-center justify-between text-xs p-2 rounded bg-background/50">
                                                                                    <span className="font-medium">{gene.gene}</span>
                                                                                    <div className="flex items-center gap-3 text-muted-foreground">
                                                                                        <span>log2FC = {gene.log2_fold_change.toFixed(2)}</span>
                                                                                        <span>p = {gene.adjusted_p_value.toExponential(2)}</span>
                                                                                        {gene.significant && (
                                                                                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-green-500/20 text-green-600 dark:text-green-400">
                                                                                                Significant
                                                                                            </span>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                            ))}
                                                                        </div>
                                                                    </div>
                                                                )}
                                                                
                                                                {analysis.top_downregulated && analysis.top_downregulated.length > 0 && (
                                                                    <div className="mb-3">
                                                                        <p className="text-xs font-medium text-muted-foreground mb-2">
                                                                            Top Downregulated Genes (in {analysis.group1}):
                                                                        </p>
                                                                        <div className="space-y-1">
                                                                            {analysis.top_downregulated.slice(0, 10).map((gene: any, geneIdx: number) => (
                                                                                <div key={geneIdx} className="flex items-center justify-between text-xs p-2 rounded bg-background/50">
                                                                                    <span className="font-medium">{gene.gene}</span>
                                                                                    <div className="flex items-center gap-3 text-muted-foreground">
                                                                                        <span>log2FC = {gene.log2_fold_change.toFixed(2)}</span>
                                                                                        <span>p = {gene.adjusted_p_value.toExponential(2)}</span>
                                                                                        {gene.significant && (
                                                                                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-green-500/20 text-green-600 dark:text-green-400">
                                                                                                Significant
                                                                                            </span>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                            ))}
                                                                        </div>
                                                                    </div>
                                                                )}
                                                            </>
                                                        )}
                                                        
                                                        {analysis.pathway_enrichment && analysis.pathway_enrichment.pathways && analysis.pathway_enrichment.pathways.length > 0 && (
                                                            <div className="mt-3 pt-3 border-t border-border">
                                                                <p className="text-xs font-medium text-muted-foreground mb-2">
                                                                    Enriched Pathways ({analysis.pathway_enrichment.total_pathways} total):
                                                                </p>
                                                                <div className="space-y-1 max-h-48 overflow-y-auto">
                                                                    {analysis.pathway_enrichment.top_pathways?.slice(0, 10).map((pathway: any, pathwayIdx: number) => (
                                                                        <div key={pathwayIdx} className="flex items-center justify-between text-xs p-2 rounded bg-background/50">
                                                                            <span className="font-medium flex-1">{pathway.pathway}</span>
                                                                            <div className="flex items-center gap-2 text-muted-foreground ml-2">
                                                                                <span className="text-[10px]">
                                                                                    p = {pathway.adjusted_p_value?.toExponential(2) || pathway.p_value?.toExponential(2) || 'N/A'}
                                                                                </span>
                                                                                {pathway.odds_ratio && (
                                                                                    <span className="text-[10px]">
                                                                                        OR = {pathway.odds_ratio.toFixed(2)}
                                                                                    </span>
                                                                                )}
                                                                                {pathway.adjusted_p_value && pathway.adjusted_p_value < 0.05 && (
                                                                                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-green-500/20 text-green-600 dark:text-green-400">
                                                                                        Significant
                                                                                    </span>
                                                                                )}
                                                                            </div>
                                                                        </div>
                                                                    ))}
                                                                </div>
                                                                {analysis.pathway_enrichment.gene_set && (
                                                                    <p className="text-[10px] text-muted-foreground mt-2">
                                                                        Gene set: {analysis.pathway_enrichment.gene_set.replace(/_/g, ' ')}
                                                                    </p>
                                                                )}
                                                            </div>
                                                        )}
                                                        
                                                        {analysis.interpretation && (
                                                            <div className="mt-3 pt-3 border-t border-border">
                                                                <p className="text-xs text-muted-foreground italic">
                                                                    {analysis.interpretation}
                                                                </p>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                    
                                    {/* Display papers if available */}
                                    {message.papers && message.papers.length > 0 && (
                                        <div className="mt-4 pt-4 border-t border-border">
                                            <h4 className="text-sm font-semibold mb-3 flex items-center gap-2">
                                                <Sparkles className="w-4 h-4" />
                                                Sources ({message.papers.length} papers found)
                                            </h4>
                                            <div className="space-y-2">
                                                {message.papers.map((paper, idx) => (
                                                    <div 
                                                        key={idx}
                                                        className="p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors"
                                                    >
                                                        <div className="flex items-start gap-2">
                                                            <span className="text-xs font-medium text-muted-foreground mt-0.5">
                                                                {idx + 1}.
                                                            </span>
                                                            <div className="flex-1 min-w-0">
                                                                {paper.link ? (
                                                                    <a 
                                                                        href={paper.link}
                                                                        target="_blank"
                                                                        rel="noopener noreferrer"
                                                                        className="text-sm font-medium text-primary hover:underline break-words"
                                                                    >
                                                                        {paper.title}
                                                                    </a>
                                                                ) : (
                                                                    <p className="text-sm font-medium break-words">
                                                                        {paper.title}
                                                                    </p>
                                                                )}
                                                                {paper.snippet && (
                                                                    <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                                                        {paper.snippet}
                                                                    </p>
                                                                )}
                                                                {(paper.authors || paper.journal || paper.year || paper.source) && (
                                                                    <p className="text-xs text-muted-foreground mt-1">
                                                                        {paper.authors && <span>{paper.authors}</span>}
                                                                        {paper.journal && <span> • {paper.journal}</span>}
                                                                        {paper.year && <span> ({paper.year})</span>}
                                                                        {paper.source && <span> • {paper.source}</span>}
                                                                    </p>
                                                                )}
                                                            </div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </CardContent>
                                {message.role === "assistant" && (
                                    <button
                                        onClick={() => handleCopy(message.content, index)}
                                        className="absolute top-2 right-2 p-1.5 rounded-md hover:bg-muted opacity-0 group-hover:opacity-100 transition-opacity"
                                        title="Copy to clipboard"
                                    >
                                        {copiedIndex === index ? (
                                            <Check className="w-4 h-4 text-green-500" />
                                        ) : (
                                            <Copy className="w-4 h-4" />
                                        )}
                                    </button>
                                )}
                            </Card>
                            {message.role === "user" && (
                                <div className="flex-shrink-0">
                                    <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center">
                                        <span className="text-sm font-medium">U</span>
                                    </div>
                                </div>
                            )}
                        </div>
                    ))}
                    {isLoading && (
                        <div className="flex gap-3">
                            <div className="flex-shrink-0">
                                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center">
                                    <Loader2 className="w-4 h-4 text-white animate-spin" />
                                </div>
                            </div>
                            <Card className="bg-card">
                                <CardContent className="p-4">
                                    <p className="text-sm text-muted-foreground">
                                        Analyzing your request...
                                    </p>
                                </CardContent>
                            </Card>
                        </div>
                    )}
                </div>
            </ScrollArea>

            {/* Suggestions */}
            {messages.length === 1 && !isLoading && (
                <div className="px-6 pb-4">
                    <div className="max-w-4xl mx-auto">
                        <p className="text-sm text-muted-foreground mb-3">Try asking:</p>
                        <div className="grid grid-cols-2 gap-2">
                            {suggestions.map((suggestion, index) => (
                                <button
                                    key={index}
                                    onClick={() => handleSuggestionClick(suggestion)}
                                    className="text-left text-sm p-3 rounded-lg border border-border hover:bg-accent hover:border-primary transition-all"
                                >
                                    {suggestion}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* Input */}
            <div className="border-t border-border p-6">
                <div className="max-w-4xl mx-auto flex gap-2">
                    <Input
                        placeholder="Ask about genes, datasets, or analyses..."
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyPress={(e) => e.key === "Enter" && handleSend()}
                        disabled={isLoading}
                        className="flex-1"
                    />
                    <Button onClick={handleSend} disabled={isLoading || !input.trim()}>
                        {isLoading ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                            <Send className="w-4 h-4" />
                        )}
                    </Button>
                </div>
            </div>
        </div>
    )
}
