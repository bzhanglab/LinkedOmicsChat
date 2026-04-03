/**
 * Authentication API and utilities
 */
import axios from "axios"

// Define API_URL locally to avoid circular dependency with api.ts.
// Match api.ts behavior so auth requests work on LAN and deployed hostnames too.
function resolveApiUrl(): string {
    if (typeof window !== "undefined") {
        const hostname = window.location.hostname
        if (hostname !== "localhost" && hostname !== "127.0.0.1") {
            return `http://${hostname}:8000`
        }
    }
    return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
}

const API_URL = resolveApiUrl()

export interface User {
    id: string
    username: string
    email: string
    is_active: boolean
    is_admin: boolean
    created_at: number
}

export interface LoginRequest {
    username: string
    password: string
}

export interface RegisterRequest {
    username: string
    email: string
    password: string
}

export interface TokenResponse {
    access_token: string
    token_type: string
}

export interface ForgotPasswordRequest {
    username: string
    email: string
}

export interface ForgotPasswordResponse {
    message: string
    reset_token: string
    expires_in: string
    note: string
}

export interface ResetPasswordRequest {
    token: string
    new_password: string
}

export interface ResetPasswordResponse {
    message: string
}

export interface PublicRuntimeConfig {
    llm_provider: string
    llm_model: string
    temperature: number
    max_tokens: number
    architecture: string
    orchestration: string
}

const AUTH_TOKEN_KEY = "linkedomicsai-auth-token"

// Auth calls should never hang the whole UI.
// Use a short timeout so the app can recover (and force re-login if needed).
const authHttp = axios.create({
    baseURL: API_URL,
    timeout: 15000, // 15s
    headers: {
        "Content-Type": "application/json",
    },
})

export const authAPI = {
    /**
     * Register a new user
     */
    async register(data: RegisterRequest): Promise<User> {
        const response = await authHttp.post<User>(`/api/v1/auth/register`, data)
        return response.data
    },

    /**
     * Login and get access token
     */
    async login(data: LoginRequest): Promise<TokenResponse> {
        const response = await authHttp.post<TokenResponse>(`/api/v1/auth/login`, data)
        return response.data
    },

    /**
     * Get current user info
     */
    async getCurrentUser(): Promise<User> {
        const token = getAuthToken()
        if (!token) {
            throw new Error("No authentication token")
        }

        const response = await authHttp.get<User>(`/api/v1/auth/me`, {
            headers: {
                Authorization: `Bearer ${token}`,
            },
            timeout: 3000, // tight — this blocks the initial page render
        })
        return response.data
    },

    /**
     * Get safe server runtime configuration for read-only UI.
     */
    async getPublicRuntimeConfig(): Promise<PublicRuntimeConfig> {
        const response = await authHttp.get<PublicRuntimeConfig>(`/api/v1/auth/public-config`, {
            timeout: 5000,
        })
        return response.data
    },

    /**
     * Request password reset
     */
    async forgotPassword(data: ForgotPasswordRequest): Promise<ForgotPasswordResponse> {
        const response = await authHttp.post<ForgotPasswordResponse>(`/api/v1/auth/forgot-password`, data)
        return response.data
    },

    /**
     * Reset password with token
     */
    async resetPassword(data: ResetPasswordRequest): Promise<ResetPasswordResponse> {
        const response = await authHttp.post<ResetPasswordResponse>(`/api/v1/auth/reset-password`, data)
        return response.data
    },
}

/**
 * Store authentication token in localStorage
 */
export function setAuthToken(token: string): void {
    if (typeof window !== "undefined") {
        localStorage.setItem(AUTH_TOKEN_KEY, token)
    }
}

/**
 * Get authentication token from localStorage
 */
export function getAuthToken(): string | null {
    if (typeof window !== "undefined") {
        return localStorage.getItem(AUTH_TOKEN_KEY)
    }
    return null
}

/**
 * Remove authentication token from localStorage
 */
export function removeAuthToken(): void {
    if (typeof window !== "undefined") {
        localStorage.removeItem(AUTH_TOKEN_KEY)
    }
}

/**
 * Check if user is authenticated
 */
export function isAuthenticated(): boolean {
    return getAuthToken() !== null
}
