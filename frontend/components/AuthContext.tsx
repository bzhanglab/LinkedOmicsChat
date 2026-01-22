"use client"

import React, { createContext, useContext, useState, useEffect } from "react"
import { User, authAPI, getAuthToken, setAuthToken, removeAuthToken } from "@/lib/auth"
import { useRouter } from "next/navigation"

interface AuthContextType {
    user: User | null
    loading: boolean
    login: (username: string, password: string) => Promise<void>
    register: (username: string, email: string, password: string) => Promise<void>
    logout: () => void
    isAuthenticated: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<User | null>(null)
    const [loading, setLoading] = useState(true)
    const router = useRouter()

    // Load user on mount if token exists
    useEffect(() => {
        const token = getAuthToken()
        if (token) {
            authAPI.getCurrentUser()
                .then(setUser)
                .catch(() => {
                    // Token invalid, remove it
                    removeAuthToken()
                    setUser(null)
                })
                .finally(() => setLoading(false))
        } else {
            setLoading(false)
        }
    }, [])

    const login = async (username: string, password: string) => {
        try {
            const response = await authAPI.login({ username, password })
            setAuthToken(response.access_token)
            const userData = await authAPI.getCurrentUser()
            setUser(userData)
        } catch (error: any) {
            throw new Error(error.response?.data?.detail || "Login failed")
        }
    }

    const register = async (username: string, email: string, password: string) => {
        try {
            await authAPI.register({ username, email, password })
            // After registration, automatically log in
            await login(username, password)
        } catch (error: any) {
            throw new Error(error.response?.data?.detail || "Registration failed")
        }
    }

    const logout = () => {
        try {
            removeAuthToken()
            setUser(null)
            // Use window.location for a hard redirect to ensure clean state
            if (typeof window !== "undefined") {
                window.location.href = "/login"
            } else {
                router.push("/login")
            }
        } catch (error) {
            console.error("Error during logout:", error)
            // Fallback: try router if window.location fails
            router.push("/login")
        }
    }

    return (
        <AuthContext.Provider
            value={{
                user,
                loading,
                login,
                register,
                logout,
                isAuthenticated: user !== null,
            }}
        >
            {children}
        </AuthContext.Provider>
    )
}

export function useAuth() {
    const context = useContext(AuthContext)
    if (context === undefined) {
        throw new Error("useAuth must be used within an AuthProvider")
    }
    return context
}
