"use client"

import React, { createContext, useContext, useState, useEffect } from "react"
import { User, authAPI, getAuthToken, setAuthToken, removeAuthToken, type RegistrationResponse } from "@/lib/auth"
import { useRouter } from "next/navigation"

interface AuthContextType {
    user: User | null
    loading: boolean
    isGuest: boolean
    login: (username: string, password: string) => Promise<void>
    register: (username: string, email: string, password: string) => Promise<RegistrationResponse>
    logout: () => void
    enterGuestMode: () => void
    isAuthenticated: boolean
    isResolvingUser: boolean
    authError: string | null
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

const GUEST_KEY = "linkedomicsai-guest-mode"
const CURRENT_SESSION_KEY = "linkedomicsai-current-session"

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<User | null>(null)
    // Initialize isGuest synchronously to avoid a flash where loading=false && isGuest=false
    // causes page.tsx to fire a redirect to /login before the useEffect can restore guest mode.
    const [isGuest, setIsGuest] = useState<boolean>(() => {
        if (typeof window !== "undefined") {
            return sessionStorage.getItem(GUEST_KEY) === "true"
        }
        return false
    })
    const [hasStoredToken, setHasStoredToken] = useState<boolean>(() => {
        if (typeof window !== "undefined") {
            return getAuthToken() !== null
        }
        return false
    })
    const [loading, setLoading] = useState(true)
    const [isResolvingUser, setIsResolvingUser] = useState(false)
    const [authError, setAuthError] = useState<string | null>(null)
    const router = useRouter()

    // Load user on mount if token exists
    useEffect(() => {
        let cancelled = false

        // Guest mode is already restored synchronously above; just stop loading.
        if (isGuest) {
            if (!cancelled) {
                setIsResolvingUser(false)
                setAuthError(null)
            }
            if (!cancelled) setLoading(false)
            return () => { cancelled = true }
        }

        const token = getAuthToken()
        setHasStoredToken(!!token)

        // Do not block the whole app on auth revalidation when we already have
        // a stored token. Let the UI become interactive immediately and validate
        // the token in the background.
        if (!cancelled) setLoading(false)

        if (token) {
            if (!cancelled) {
                setIsResolvingUser(true)
                setAuthError(null)
            }
            authAPI
                .getCurrentUser()
                .then((u) => {
                    if (!cancelled && getAuthToken() === token) {
                        setUser(u)
                        setAuthError(null)
                    }
                })
                .catch((err) => {
                    // Only clear the token on an explicit 401 (token actually invalid/expired).
                    // Network errors, timeouts, and server restarts should NOT log the user out.
                    const status = err?.response?.status
                    if (status === 401 && getAuthToken() === token) {
                        removeAuthToken()
                        if (!cancelled) {
                            setUser(null)
                            setHasStoredToken(false)
                            setAuthError("Your session expired. Please sign in again.")
                        }
                    } else if (!cancelled && getAuthToken() === token) {
                        setAuthError(err?.response?.data?.detail || err?.message || "Could not refresh your account session.")
                    }
                    // For all other errors (network, 5xx, timeout) keep the token and stay logged in.
                })
                .finally(() => {
                    if (!cancelled) {
                        setIsResolvingUser(false)
                    }
                })
        } else {
            setUser(null)
            setIsResolvingUser(false)
            setAuthError(null)
        }

        return () => {
            cancelled = true
        }
    }, [isGuest])

    const login = async (username: string, password: string) => {
        try {
            const response = await authAPI.login({ username, password })
            setAuthToken(response.access_token)
            setHasStoredToken(true)
            const userData = await authAPI.getCurrentUser()
            if (typeof window !== "undefined") {
                sessionStorage.removeItem(GUEST_KEY)
            }
            setIsGuest(false)
            setUser(userData)
            setAuthError(null)
            setIsResolvingUser(false)
            localStorage.setItem("linkedomicsai-has-visited", "1")
        } catch (error: any) {
            throw new Error(error.response?.data?.detail || "Login failed")
        }
    }

    const register = async (username: string, email: string, password: string) => {
        try {
            const response = await authAPI.register({ username, email, password })
            if (response.auto_login) {
                await login(username, password)
            }
            return response
        } catch (error: any) {
            throw new Error(error.response?.data?.detail || "Registration failed")
        }
    }

    const enterGuestMode = () => {
        removeAuthToken()
        setUser(null)
        setHasStoredToken(false)
        setAuthError(null)
        setIsResolvingUser(false)
        setLoading(false)
        if (typeof window !== "undefined") {
            sessionStorage.setItem(GUEST_KEY, "true")
            localStorage.removeItem(CURRENT_SESSION_KEY)
        }
        setIsGuest(true)
    }

    const logout = () => {
        try {
            removeAuthToken()
            setUser(null)
            setIsGuest(false)
            setHasStoredToken(false)
            setAuthError(null)
            setIsResolvingUser(false)
            if (typeof window !== "undefined") {
                sessionStorage.removeItem(GUEST_KEY)
                localStorage.removeItem(CURRENT_SESSION_KEY)
                window.location.href = "/login"
            } else {
                router.push("/login")
            }
        } catch (error) {
            console.error("Error during logout:", error)
            router.push("/login")
        }
    }

    return (
        <AuthContext.Provider
            value={{
                user,
                loading,
                isGuest,
                login,
                register,
                logout,
                enterGuestMode,
                isAuthenticated: user !== null || isGuest || hasStoredToken,
                isResolvingUser,
                authError,
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
