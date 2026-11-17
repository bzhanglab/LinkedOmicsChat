"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { useAuth } from "@/components/AuthContext"

export default function LoginPage() {
    const [username, setUsername] = useState("")
    const [password, setPassword] = useState("")
    const [error, setError] = useState("")
    const [loading, setLoading] = useState(false)
    const { login, enterGuestMode, user, loading: authLoading } = useAuth()
    const router = useRouter()

    useEffect(() => {
        if (!authLoading && user) router.push("/")
    }, [authLoading, user, router])

    const handleGuestMode = () => {
        enterGuestMode()
        window.location.href = "/"
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError("")
        setLoading(true)
        try {
            await login(username, password)
            router.push("/")
        } catch (err: any) {
            setError(err.message || "Login failed. Please check your credentials.")
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="min-h-screen flex flex-col items-center justify-center relative overflow-hidden bg-slate-50">

            {/* ── Content ── */}
            <div className="relative z-10 w-full max-w-sm px-4 py-12 flex flex-col gap-8">

                {/* Brand + tagline */}
                <div className="text-center space-y-3">
                    <Link href="/welcome" className="inline-flex flex-col items-center gap-2 hover:opacity-80 transition-opacity">
                        <img src="/logo.png" alt="LinkedOmicsChat" className="h-12 w-auto" />
                        <span className="text-slate-800 text-4xl font-bold tracking-tight">LinkedOmics<span className="text-teal-600">Chat</span></span>
                    </Link>
                    <p className="text-slate-500 text-sm">
                        Ask cancer multi-omics questions in plain English: TCGA, CPTAC, clinical trial datasets, and literature.
                    </p>
                </div>

                {/* ── Glass card ── */}
                <div className="glass-card-light rounded-3xl px-6 py-7 space-y-5">

                    <h2 className="text-slate-800 text-lg font-semibold">Sign in</h2>

                    {error && (
                        <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-red-50 border border-red-200 text-red-600 text-sm">
                            <svg className="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                            </svg>
                            <span>
                                {error}
                                {error.toLowerCase().includes("verify your email") && (
                                    <>
                                        {" "}
                                        <Link href="/verify-email" className="underline hover:text-red-700">
                                            Resend verification
                                        </Link>
                                    </>
                                )}
                            </span>
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div>
                            <label htmlFor="username" className="block text-sm font-medium text-slate-700 mb-1.5">
                                Username
                            </label>
                            <input
                                id="username"
                                type="text"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                required
                                placeholder="Enter your username"
                                autoComplete="username"
                                className="glass-input-light w-full px-3.5 py-2.5 rounded-xl text-sm transition-all"
                            />
                        </div>

                        <div>
                            <div className="flex items-center justify-between mb-1.5">
                                <label htmlFor="password" className="block text-sm font-medium text-slate-700">
                                    Password
                                </label>
                                <Link href="/forgot-password" className="text-xs text-teal-600 hover:text-teal-700 hover:underline">
                                    Forgot password?
                                </Link>
                            </div>
                            <input
                                id="password"
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                placeholder="Enter your password"
                                autoComplete="current-password"
                                className="glass-input-light w-full px-3.5 py-2.5 rounded-xl text-sm transition-all"
                            />
                        </div>

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full py-2.5 px-4 rounded-xl bg-teal-600 hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium text-sm transition-all shadow-sm shadow-teal-200"
                        >
                            {loading ? "Signing in…" : "Sign in"}
                        </button>
                    </form>

                    <p className="text-center text-sm text-slate-500">
                        No account?{" "}
                        <Link href="/register" className="text-teal-600 hover:text-teal-700 hover:underline font-medium">
                            Sign up
                        </Link>
                    </p>

                    <div className="flex items-center gap-3">
                        <div className="flex-1 border-t border-slate-200" />
                        <span className="text-xs text-slate-400">or</span>
                        <div className="flex-1 border-t border-slate-200" />
                    </div>

                    <div className="space-y-2">
                        <button
                            type="button"
                            onClick={handleGuestMode}
                            className="w-full py-3 px-4 rounded-xl border-2 border-teal-500 bg-teal-50 hover:bg-teal-100 text-teal-700 text-sm font-semibold transition-all inline-flex items-center justify-center gap-2"
                        >
                            Continue as Guest
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
                            </svg>
                        </button>
                        <p className="text-center text-xs text-slate-400 leading-relaxed">
                            Guest access is rate-limited and sessions are not saved.{" "}
                            <Link href="/register" className="underline hover:text-slate-600">
                                Sign up
                            </Link>{" "}
                            for a higher limit and saved history.
                        </p>
                    </div>
                </div>

                <p className="text-center text-xs text-slate-400">
                    © 2026 Zhang Lab · Free to use · Source code under the{" "}
                    <a href="https://github.com/bzhanglab/LinkedOmicsChat/blob/main/LICENSE" target="_blank" rel="noopener noreferrer" className="underline hover:text-slate-600 transition-colors">MIT License</a>
                </p>
            </div>
        </div>
    )
}
