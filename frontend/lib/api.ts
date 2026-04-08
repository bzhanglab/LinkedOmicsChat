import axios from "axios"
import { getAuthToken } from "./auth"

// Dynamically derive the API URL from the current browser hostname.
// This makes the app work correctly regardless of whether it's accessed via
// localhost, a LAN IP address, or a domain name — no env var restart needed.
function resolveApiUrl(): string {
    if (typeof window !== "undefined") {
        const hostname = window.location.hostname
        if (hostname !== "localhost" && hostname !== "127.0.0.1") {
            return `http://${hostname}:8000`
        }
    }
    return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
}

export const API_URL = resolveApiUrl()

// Map raw backend status strings to user-friendly messages.
// Handles both "Running <tool>..." patterns and fixed phrases.
const TOOL_STATUS_LABELS: Record<string, string> = {
    // LinkedOmics / expression tools
    "cancer_gene_expression":         "Querying expression data...",
    "get_cis_correlations":           "Fetching cis-correlations...",
    "get_trans_correlations":         "Fetching trans-correlations...",
    "overall_survival_per_cancer":    "Running survival analysis...",
    "clinical_trial_information":           "Looking up clinical trials...",
    "batch_clinical_trial_information":     "Looking up clinical trials...",
    "get_study_info":                       "Fetching study details...",
    "gene_set_trial_information":           "Looking up pathway trial associations...",
    "filter_clinical_trials":              "Filtering clinical studies...",
    "meta_analysis_predictive_genes":       "Running gene meta-analysis...",
    "meta_analysis_predictive_gene_sets":   "Running pathway meta-analysis...",
    "get_study_predictive_genes":           "Fetching study gene rankings...",
    "get_study_predictive_gene_sets":       "Fetching study pathway rankings...",
    // FunMap / network
    "funmap_neighborhood":            "Exploring functional network...",
    "get_target":                     "Checking drug targets...",
    // Enrichment / pathways
    "webgestalt":                     "Running pathway enrichment...",
    // Literature
    "search_literature":              "Searching literature...",
    "pubmed_search":                  "Searching PubMed...",
    // CPTAC
    "get_cptac_proteomics":           "Fetching proteomics data...",
    "get_cptac_transcriptomics":      "Fetching transcriptomics data...",
    "get_cptac_phosphoproteomics":    "Fetching phosphoproteomics data...",
    "get_cptac_clinical":             "Fetching clinical data...",
    "list_cptac_datasets":            "Loading CPTAC datasets...",
}

const FIXED_STATUS_LABELS: Record<string, string> = {
    "Initializing session...":        "Starting up...",
    "Analyzing query requirements...":"Understanding your question...",
    "Analyzing tool results...":      "Interpreting results...",
    "Drafting final analysis...":     "Writing response...",
    "Formatting response...":         "Finalizing...",
}

export function friendlyStatus(raw: string): string {
    // Fixed phrase mapping
    if (FIXED_STATUS_LABELS[raw]) return FIXED_STATUS_LABELS[raw]

    // "Running <server>::<tool>..." or "Running <server>__<tool>..." or "Running <tool>..."
    const runMatch = raw.match(/^Running\s+(.+?)\.{0,3}$/i)
    if (runMatch) {
        const fullName = runMatch[1].trim()
        // Strip namespace prefix — tools arrive as "linkedomics__tool" or "linkedomics::tool"
        const bareName = fullName.includes("::") ? fullName.split("::").pop()!
                       : fullName.includes("__") ? fullName.split("__").pop()!
                       : fullName
        if (TOOL_STATUS_LABELS[bareName]) return TOOL_STATUS_LABELS[bareName]
        if (TOOL_STATUS_LABELS[fullName]) return TOOL_STATUS_LABELS[fullName]
        return "Retrieving data..."
    }

    return raw
}

const api = axios.create({
    baseURL: API_URL,
    timeout: 180000, // 3 minutes for complex analyses like differential expression
    headers: {
        "Content-Type": "application/json",
    },
})

// Add auth token to all requests
api.interceptors.request.use(
    (config) => {
        const token = getAuthToken()
        if (token) {
            config.headers.Authorization = `Bearer ${token}`
        }
        return config
    },
    (error) => {
        return Promise.reject(error)
    }
)

// Handle 401 errors (unauthorized) - redirect to login
api.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            const token = getAuthToken()
            const isGuest =
                typeof window !== "undefined" &&
                sessionStorage.getItem("linkedomicsai-guest-mode") === "true"

            // Only force-login users with an actual auth token.
            if (typeof window !== "undefined" && token && !isGuest) {
                window.location.href = "/login"
            }
        }
        return Promise.reject(error)
    }
)

export interface Paper {
    title: string
    link?: string
    snippet?: string
    source?: string
    authors?: string
    journal?: string
    year?: number
}

export interface PathwayEnrichment {
    gene_set?: string
    total_pathways?: number
    genes?: string[]
    pathways?: Array<{
        pathway: string
        p_value: number
        adjusted_p_value: number
        odds_ratio?: number
        genes_in_pathway?: number
        genes_in_list?: number
        gene_ratio?: number
        enrichment_score?: number
    }>
    top_pathways?: Array<{
        pathway: string
        p_value: number
        adjusted_p_value: number
        odds_ratio?: number
        genes_in_pathway?: number
        genes_in_list?: number
        gene_ratio?: number
        enrichment_score?: number
    }>
}

export interface AnalysisResult {
    analysis_type?: string
    target_gene?: string
    cancer_type?: string
    data_source?: string
    data_type?: string
    total_results?: number
    significant_results?: number
    // For correlation/association analysis
    results?: Array<{
        gene: string
        correlation: number
        p_value: number
        adjusted_p_value: number
        significant: boolean
    }>
    top_correlations?: Array<{
        gene: string
        correlation: number
        p_value: number
        adjusted_p_value: number
        significant: boolean
    }>
    // For differential expression analysis
    group1?: string
    group2?: string
    group1_samples?: number
    group2_samples?: number
    method?: string
    top_upregulated?: Array<{
        gene: string
        log2_fold_change: number
        p_value: number
        adjusted_p_value: number
        significant: boolean
    }>
    top_downregulated?: Array<{
        gene: string
        log2_fold_change: number
        p_value: number
        adjusted_p_value: number
        significant: boolean
    }>
    pathway_enrichment?: PathwayEnrichment
    interpretation?: string
}

export interface StaticVisualization {
    type: "static_plot"
    id: string
    title: string
    png_b64?: string  // base64-encoded PNG (absent for historical messages — loaded on demand)
    svg?: string      // raw SVG string
    csv?: string      // CSV text for download
}

export interface NetworkVisualization {
    type: "network_plot"
    id: string
    title: string
    nodes?: Array<{ name: string; value: string }>  // absent for historical messages — loaded on demand
    edges?: Array<{ source: string; target: string }>
    csv?: string      // edge list CSV for download
}

export interface DrugDetail {
    name: string
    tier: string
    databases: Array<{ name: string; url: string }>
    indication: { name: string; url: string } | null
}

export interface DrugTargetVisualization {
    type: "drug_target_grid"
    id: string
    title: string
    gene: string
    tier?: string
    family?: string
    drugs?: string
    drug_tiers?: string
    drug_details?: DrugDetail[]
    features?: Array<{ label: string; field: string; expandable?: boolean; parent_field?: string }>
    cohorts?: string[]
    presence?: boolean[][]
    plot_map?: Record<string, Record<string, string[]>>
    table_map?: Record<string, Record<string, Record<string, string | number | null>[]>>
    hyper_sites?: Array<{ site: string; cohorts: string[] }>
    protein_cohorts?: string[]
}

export interface TargetSearchVisualization {
    type: "target_search_table"
    id: string
    title: string
    total: number
    genes?: Array<{
        gene: string
        tier: string
        family: string
        drugs: string
        antigen: string
        count?: number
        lo_score?: number
    }>
    description?: string
    score_label?: string
}

export interface PredictiveResultsTableVisualization {
    type: "predictive_results_table"
    /** "clinical_trial" renders production-style columns; default renders meta-analysis columns */
    variant?: "clinical_trial"
    /** "gene_set" uses /api/plots/gene_set/ endpoint; "treatment_gene"/"treatment_gene_set" use POST; default uses /api/plots/gene/ */
    plot_type?: "gene_set" | "treatment_gene" | "treatment_gene_set"
    id: string
    title: string
    row_label: string
    /** Gene or gene-set name used to fetch per-row expression plots */
    gene?: string
    /** Study list for treatment_gene plots — all studies in the meta-analysis */
    study_list?: string[]
    /** Optional column header overrides (used in default/meta-analysis variant) */
    col_studies?: string
    col_auroc?: string
    col_fdr?: string
    rows?: Array<{
        rank: number
        label: string
        studies?: number | string
        avg_auroc?: number
        meta_fdr?: number
        meta_fdr_signed?: number
        meta_fdr_sci?: string
        p_value?: number | null
        direction?: string
        /** Study series base ID (e.g. "GSE25066") — display only */
        series?: string
        /** Full study ID including treatment suffix (e.g. "GSE194040_Paclitaxel_AMG386.csv") — used for plot API */
        study_id?: string
        disease?: string
        subtype?: string
        response_evaluation?: string
    }>
    description?: string
}

export type AnyVisualization =
    | StaticVisualization
    | NetworkVisualization
    | DrugTargetVisualization
    | TargetSearchVisualization
    | PredictiveResultsTableVisualization

export interface ExecutionTraceToolCall {
    tool: string
    latency_ms: number
    status: "ok" | "error" | "missing" | "empty"
}

export interface ExecutionTraceStep {
    node: "agent" | "tools"
    step: number
    latency_ms: number
    tool_calls?: ExecutionTraceToolCall[]
    input_tokens?: number
    output_tokens?: number
}

export interface ChatMessage {
    role: "user" | "assistant" | "system"
    content: string
    summary?: string
    turnId?: number
    sourceMessageId?: number
    hasFullContent?: boolean
    hasImages?: boolean
    hasVisualizations?: boolean   // true when plots were stripped for history; fetch on demand
    noCollapse?: boolean  // when true, never show "Show details" button
    wasPreview?: boolean  // when true, was fetched on demand — keep collapsible regardless of length
    isGeneralKnowledge?: boolean  // true when LLM answered from training knowledge, not LinkedOmics data
    confidence?: "high" | "partial" | "low" | "general_knowledge"
    isError?: boolean  // true when this message represents an error with a retry option
    timestamp?: Date
    papers?: Paper[]
    analyses?: AnalysisResult[]
    suggestions?: string[]
    clarificationOptions?: string[]
    toolSources?: Record<string, string>
    toolsUsed?: string[]
    visualizations?: AnyVisualization[]
    executionTrace?: ExecutionTraceStep[]
}

/** Map a tool name to its human-readable data source with a URL. */
export interface DataSource {
    label: string
    url: string
}

export const TOOL_DATA_SOURCES: Record<string, DataSource> = {
    cancer_gene_expression:        { label: "LinkedOmics",         url: "https://www.linkedomics.org" },
    get_cis_correlations:          { label: "LinkedOmics",         url: "https://www.linkedomics.org" },
    get_trans_correlations:        { label: "LinkedOmics",         url: "https://www.linkedomics.org" },
    overall_survival_per_cancer:   { label: "LinkedOmics",         url: "https://www.linkedomics.org" },
    tcga_survival_analysis:        { label: "LinkedOmics TCGA",    url: "http://linkedomics.org/" },
    clinical_trial_information:    { label: "LinkedOmics Trials",  url: "https://trials.linkedomics.org" },
    funmap_neighborhood:           { label: "FunMap",              url: "https://funmap.linkedomics.org" },
    get_target:                    { label: "LinkedOmics Targets", url: "https://targets.linkedomics.org" },
    webgestalt:                    { label: "WebGestalt",          url: "https://www.webgestalt.org" },
    search_literature:             { label: "PubMed",              url: "https://pubmed.ncbi.nlm.nih.gov" },
    pubmed_search:                 { label: "PubMed",              url: "https://pubmed.ncbi.nlm.nih.gov" },
    get_cptac_proteomics:          { label: "CPTAC",              url: "https://proteomics.cancer.gov/programs/cptac" },
    get_cptac_transcriptomics:     { label: "CPTAC",              url: "https://proteomics.cancer.gov/programs/cptac" },
    get_cptac_phosphoproteomics:   { label: "CPTAC",              url: "https://proteomics.cancer.gov/programs/cptac" },
    get_cptac_clinical:            { label: "CPTAC",              url: "https://proteomics.cancer.gov/programs/cptac" },
    list_cptac_datasets:           { label: "CPTAC",              url: "https://proteomics.cancer.gov/programs/cptac" },
}

/** Short keys used in inline markdown citations → DataSource. */
export const INLINE_SOURCE_MAP: Record<string, DataSource> = {
    linkedomics: { label: "LinkedOmics", url: "https://www.linkedomics.org" },
    pubmed:      { label: "PubMed",      url: "https://pubmed.ncbi.nlm.nih.gov" },
    funmap:      { label: "FunMap",      url: "https://funmap.linkedomics.org" },
    webgestalt:  { label: "WebGestalt", url: "https://www.webgestalt.org" },
    cptac:       { label: "CPTAC",      url: "https://proteomics.cancer.gov/programs/cptac" },
    targets:     { label: "LinkedOmics Targets", url: "https://targets.linkedomics.org" },
    trials:      { label: "LinkedOmics Trials",  url: "https://trials.linkedomics.org" },
}

/** Deduplicate tools_used into a list of unique DataSource entries. */
export function resolveDataSources(toolsUsed: string[]): DataSource[] {
    const seen = new Set<string>()
    const result: DataSource[] = []
    for (const tool of toolsUsed) {
        // Tools may arrive as:
        //   "linkedomics::cancer_gene_expression"
        //   "linkedomics__cancer_gene_expression"
        //   "linkedomics__cancer_gene_expression#0"  ← _generate_response passes raw dict keys
        // Strip the instance suffix (#N), then strip the namespace prefix.
        const withoutIndex = tool.replace(/#\d+$/, "")
        const bareName = withoutIndex.includes("::")
            ? withoutIndex.split("::").pop()!
            : withoutIndex.includes("__")
            ? withoutIndex.split("__").pop()!
            : withoutIndex
        const src = TOOL_DATA_SOURCES[withoutIndex] ?? TOOL_DATA_SOURCES[bareName]
        if (src && !seen.has(src.label)) {
            seen.add(src.label)
            result.push(src)
        }
    }
    return result
}

export interface ChatRequest {
    message: string
    session_id?: string
    context?: Record<string, unknown>
}

export interface ChatResponse {
    message: string
    summary?: string
    session_id: string
    turn_id?: number
    agent_responses: Array<Record<string, unknown>>
    visualizations: Array<Record<string, unknown>>
    analyses: Array<Record<string, unknown>>  // Analysis results (correlations, etc.)
    suggestions: string[]
    clarification_options?: string[]
    tool_sources?: Record<string, string>
    tools_used?: string[]
    no_collapse?: boolean
    is_general_knowledge?: boolean
    confidence?: "high" | "partial" | "low" | "general_knowledge"
    execution_trace?: ExecutionTraceStep[]
    metadata?: Record<string, unknown>
}

export interface AdminOverview {
    total_users: number
    active_users: number
    total_sessions: number
    total_messages: number
    total_registered_queries: number
    total_guest_queries: number
    total_queries: number
    total_feedback: number
    positive_feedback: number
    negative_feedback: number
    positive_feedback_rate: number
    total_input_tokens: number
    total_output_tokens: number
    total_tokens: number
}

export interface AdminQualitySignals {
    low_confidence_responses: number
    partial_confidence_responses: number
    general_knowledge_responses: number
    no_data_responses: number
}

export interface AdminDailyActivity {
    date: string
    active_users: number
    registered_queries: number
    guest_queries: number
    feedback_count: number
    input_tokens: number
    output_tokens: number
    registered_input_tokens: number
    registered_output_tokens: number
    guest_input_tokens: number
    guest_output_tokens: number
}

export interface AdminModelUsage {
    model: string
    queries: number
    input_tokens: number
    output_tokens: number
    total_tokens: number
}

export interface AdminUserUsage {
    user_id: string
    username: string
    email: string
    queries: number
    sessions: number
    input_tokens: number
    output_tokens: number
    total_tokens: number
    last_seen_at?: number | null
}

export interface AdminFeedbackItem {
    id: number
    timestamp: number
    rating: 1 | -1
    reason?: string | null
    turn_id?: number | null
    session_id?: string | null
    username?: string | null
    email?: string | null
    query_preview: string
    message_preview: string
}

export interface AdminFeedbackAggregate {
    query: string
    positive_count: number
    negative_count: number
    total_count: number
}

export interface AdminToolUsage {
    tool: string
    count: number
}

export interface AdminRecentTurn {
    turn_id: number
    timestamp: number
    username?: string | null
    email?: string | null
    query_preview: string
    message_preview: string
    confidence?: "high" | "partial" | "low" | "general_knowledge" | null
    tools_used: string[]
    feedback_rating?: 1 | -1 | null
}

export interface AdminDashboardResponse {
    generated_at: number
    overview: AdminOverview
    quality_signals: AdminQualitySignals
    daily_activity: AdminDailyActivity[]
    model_usage: AdminModelUsage[]
    top_users: AdminUserUsage[]
    recent_feedback: AdminFeedbackItem[]
    top_feedback_targets: AdminFeedbackAggregate[]
    tool_usage: AdminToolUsage[]
    recent_turns: AdminRecentTurn[]
}

export interface Dataset {
    id: string
    name: string
    description: string
    cancer_type: string | null
    sample_count: number
    feature_count: number
    data_types: string[]
    publication: string | null
    source: string
}

export const chatAPI = {
    async sendMessage(request: ChatRequest): Promise<ChatResponse> {
        const response = await api.post<ChatResponse>("/api/v1/chat/query", request)
        return response.data
    },

    async streamMessage(
        request: ChatRequest,
        onStatus: (status: string) => void,
        onTextDelta?: (delta: string) => void
    ): Promise<ChatResponse> {
        const token = getAuthToken()
        const response = await fetch(`${API_URL}/api/v1/chat/stream`, {
            method: "POST",
            headers: {
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
                ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            cache: "no-store",
            body: JSON.stringify(request),
        })

        if (!response.ok || !response.body) {
            let detail = response.statusText
            try {
                const errBody = await response.json()
                if (errBody?.detail) detail = errBody.detail
            } catch {}
            throw new Error(detail)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""
        let finalResponse: ChatResponse | null = null

        try {
            while (true) {
                const { done, value } = await reader.read()
                if (done) break

                buffer += decoder.decode(value, { stream: true })

                // Process complete SSE messages (separated by \n\n)
                let msgEnd = buffer.indexOf("\n\n")
                while (msgEnd !== -1) {
                    const chunk = buffer.slice(0, msgEnd).trim()
                    buffer = buffer.slice(msgEnd + 2)
                    msgEnd = buffer.indexOf("\n\n")

                    if (chunk.startsWith("data: ")) {
                        try {
                            const data = JSON.parse(chunk.slice(6))
                            if (data.type === "status") {
                                onStatus(friendlyStatus(data.content))
                            } else if (data.type === "text_delta") {
                                onTextDelta?.(data.content as string)
                            } else if (data.type === "final") {
                                finalResponse = data.content as ChatResponse
                            }
                        } catch (e) {
                            console.warn("Failed to parse SSE chunk:", chunk)
                        }
                    }
                }
            }
        } finally {
            reader.releaseLock()
        }

        if (!finalResponse) {
            throw new Error("Stream closed without returning a final response.")
        }

        return finalResponse
    },

    async listSessions() {
        const response = await api.get<{
            sessions: Array<{
                session_id: string
                title: string
                created_at: number
                last_updated: number
                message_count: number
            }>
        }>("/api/v1/chat/sessions")
        return response.data
    },

    async getSession(sessionId: string) {
        const response = await api.get(`/api/v1/chat/sessions/${sessionId}`)
        return response.data
    },

    async getSessionHistory(sessionId: string, params?: { limit?: number; before?: number }) {
        const response = await api.get(`/api/v1/chat/sessions/${sessionId}/history`, {
            params,
        })
        return response.data as {
            session_id: string
            title: string
            history: Array<{ id: number; query: string; response: any; timestamp: number }>
            has_more: boolean
            next_before: number | null
        }
    },

    async getChatMessage(messageId: number) {
        const response = await api.get(`/api/v1/chat/messages/${messageId}`)
        return response.data as {
            id: number
            session_id: string
            query: string
            response: any
            timestamp: number
        }
    },

    async updateSessionTitle(sessionId: string, title: string) {
        const response = await api.patch(`/api/v1/chat/sessions/${sessionId}/title`, { title })
        return response.data
    },

    async clearSession(sessionId: string) {
        const response = await api.delete(`/api/v1/chat/sessions/${sessionId}`)
        return response.data
    },

    async truncateSessionFromMessage(sessionId: string, messageId: number) {
        const response = await api.post(`/api/v1/chat/sessions/${sessionId}/truncate`, {
            message_id: messageId,
        })
        return response.data as {
            message: string
            session_id: string
            deleted_turns: number
            remaining_turns: number
        }
    },

    async shareSession(sessionId: string): Promise<{ shared_token: string }> {
        const response = await api.post(`/api/v1/chat/sessions/${sessionId}/share`)
        return response.data
    },

    async getSharedSession(token: string) {
        const response = await api.get(`/api/v1/chat/shared/${token}`)
        return response.data
    },

    async getVisualization(vizId: string): Promise<Record<string, unknown>> {
        const response = await api.get(`/api/v1/chat/visualizations/${vizId}`)
        return response.data
    },

    async submitFeedback(payload: {
        turn_id?: number
        session_id?: string
        rating: 1 | -1
        reason?: string
    }): Promise<void> {
        await api.post("/api/v1/chat/feedback", payload)
    },

    async searchMessages(q: string, limit = 20) {
        const response = await api.get<{
            results: Array<{
                message_id: number
                session_id: string
                session_title: string
                query: string
                excerpt: string
                timestamp: number
            }>
            query: string
            count: number
        }>("/api/v1/chat/search", { params: { q, limit } })
        return response.data
    },
}

export const adminAPI = {
    async getDashboard(): Promise<AdminDashboardResponse> {
        const response = await api.get<AdminDashboardResponse>("/api/v1/admin/dashboard")
        return response.data
    },
}

export const datasetsAPI = {
    async list(filters?: {
        cancer_type?: string
        data_type?: string
        source?: string
    }): Promise<Dataset[]> {
        const response = await api.get<Dataset[]>("/api/v1/datasets/", { params: filters })
        return response.data
    },

    async get(datasetId: string): Promise<Dataset> {
        const response = await api.get<Dataset>(`/api/v1/datasets/${datasetId}`)
        return response.data
    },

    async search(query: string) {
        const response = await api.post("/api/v1/datasets/search", { text: query })
        return response.data
    },
}

export const agentsAPI = {
    async list() {
        const response = await api.get("/api/v1/agents/")
        return response.data
    },

    async process(agentId: string, query: string, context?: Record<string, unknown>) {
        const response = await api.post(`/api/v1/agents/${agentId}/process`, {
            query,
            context,
        })
        return response.data
    },

    async getStatus(agentId: string) {
        const response = await api.get(`/api/v1/agents/${agentId}/status`)
        return response.data
    },
}

export const workflowsAPI = {
    async list(status?: string) {
        const response = await api.get("/api/v1/workflows/", { params: { status } })
        return response.data
    },

    async get(workflowId: string) {
        const response = await api.get(`/api/v1/workflows/${workflowId}`)
        return response.data
    },

    async getStatus(workflowId: string) {
        const response = await api.get(`/api/v1/workflows/${workflowId}/status`)
        return response.data
    },

    async getResults(workflowId: string) {
        const response = await api.get(`/api/v1/workflows/${workflowId}/results`)
        return response.data
    },

    async create(workflow: Record<string, unknown>) {
        const response = await api.post("/api/v1/workflows/", workflow)
        return response.data
    },

    async execute(workflowId: string, parameters?: Record<string, unknown>) {
        console.log("📡 API: Executing workflow", workflowId, "with params:", parameters)
        try {
            const response = await api.post(`/api/v1/workflows/${workflowId}/execute`, parameters || {}, {
                headers: { "Content-Type": "application/json" }
            })
            console.log("✅ API: Response received:", response.data)
            return response.data
        } catch (error: any) {
            console.error("❌ API: Error executing workflow:", error)
            console.error("❌ API: Error response:", error.response?.data)
            throw error
        }
    },

    async delete(workflowId: string) {
        const response = await api.delete(`/api/v1/workflows/${workflowId}`)
        return response.data
    },

    async createFromTemplate(templateName: string) {
        const response = await api.post(`/api/v1/workflows/templates/${templateName}`)
        return response.data
    },

    async seedExamples() {
        const response = await api.post("/api/v1/workflows/seed-examples")
        return response.data
    },
}

export const toolsAPI = {
    async list() {
        // Returns { tools: { toolName: meta... } }
        const response = await api.get<{ tools: Record<string, any> }>("/api/v1/tools/")
        return response.data
    },

    async execute(toolId: string, args: Record<string, any>) {
        const response = await api.post("/api/v1/tools/execute", {
            tool_id: toolId,
            arguments: args
        })
        return response.data
    }
}

export default api
