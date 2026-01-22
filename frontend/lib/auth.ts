/**
 * Authentication API and utilities
 */
import axios from "axios"
import { API_URL } from "./api"

export interface User {
    id: string
    username: string
    email: string
    is_active: boolean
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

const AUTH_TOKEN_KEY = "cpgagent-auth-token"

export const authAPI = {
    /**
     * Register a new user
     */
    async register(data: RegisterRequest): Promise<User> {
        const response = await axios.post<User>(
            `${API_URL}/api/v1/auth/register`,
            data
        )
        return response.data
    },

    /**
     * Login and get access token
     */
    async login(data: LoginRequest): Promise<TokenResponse> {
        const response = await axios.post<TokenResponse>(
            `${API_URL}/api/v1/auth/login`,
            data
        )
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

        const response = await axios.get<User>(
            `${API_URL}/api/v1/auth/me`,
            {
                headers: {
                    Authorization: `Bearer ${token}`
                }
            }
        )
        return response.data
    },

    /**
     * Request password reset
     */
    async forgotPassword(data: ForgotPasswordRequest): Promise<ForgotPasswordResponse> {
        const response = await axios.post<ForgotPasswordResponse>(
            `${API_URL}/api/v1/auth/forgot-password`,
            data
        )
        return response.data
    },

    /**
     * Reset password with token
     */
    async resetPassword(data: ResetPasswordRequest): Promise<ResetPasswordResponse> {
        const response = await axios.post<ResetPasswordResponse>(
            `${API_URL}/api/v1/auth/reset-password`,
            data
        )
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
