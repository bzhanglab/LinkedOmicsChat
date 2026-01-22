import axios from "axios"

export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

const api = axios.create({
    baseURL: API_URL,
    timeout: 180000, // 3 minutes for complex analyses like differential expression
    headers: {
        "Content-Type": "application/json",
    },
})

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

export interface ChatMessage {
    role: "user" | "assistant" | "system"
    content: string
    timestamp?: Date
    papers?: Paper[]
    analyses?: AnalysisResult[]
}

export interface ChatRequest {
    message: string
    session_id?: string
    context?: Record<string, unknown>
}

export interface ChatResponse {
    message: string
    session_id: string
    agent_responses: Array<Record<string, unknown>>
    visualizations: Array<Record<string, unknown>>
    analyses: Array<Record<string, unknown>>  // Analysis results (correlations, etc.)
    suggestions: string[]
    metadata?: Record<string, unknown>
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

    async getSession(sessionId: string) {
        const response = await api.get(`/api/v1/chat/sessions/${sessionId}`)
        return response.data
    },

    async clearSession(sessionId: string) {
        const response = await api.delete(`/api/v1/chat/sessions/${sessionId}`)
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

export default api
