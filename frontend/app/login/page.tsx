"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { useAuth } from "@/components/AuthContext"

const features = [
    {
        label: "CPTAC proteomics",
        icon: (
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15M14.25 3.104c.251.023.501.05.75.082M19.8 15l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23-.607L5 14.5m14.8.5-2.6.65a9 9 0 01-10.4 0L4.2 15M5 14.5v6m14-6v6" />
            </svg>
        ),
    },
    {
        label: "LinkedOmics networks",
        icon: (
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622 1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
            </svg>
        ),
    },
    {
        label: "PubMed literature",
        icon: (
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
            </svg>
        ),
    },
]

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
                        Natural language interface to TCGA, CPTAC, and biomedical literature.
                    </p>
                    <div className="flex flex-wrap justify-center gap-2 pt-1">
                        {features.map((f) => (
                            <span
                                key={f.label}
                                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-slate-600 text-xs font-medium border border-slate-200 bg-white/60"
                            >
                                {f.icon}
                                {f.label}
                            </span>
                        ))}
                    </div>
                </div>

                {/* ── Glass card ── */}
                <div className="glass-card-light rounded-3xl px-6 py-7 space-y-5">

                    <h2 className="text-slate-800 text-lg font-semibold">Sign in</h2>

                    {error && (
                        <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-red-50 border border-red-200 text-red-600 text-sm">
                            <svg className="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                            </svg>
                            {error}
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
                            Sign up free
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
                            className="w-full py-2.5 px-4 rounded-xl border border-slate-200 text-slate-600 hover:bg-slate-50 text-sm font-medium transition-all"
                        >
                            Continue as Guest
                        </button>
                        <p className="text-center text-xs text-slate-400 leading-relaxed">
                            Guest access is rate-limited and sessions are not saved.{" "}
                            <Link href="/register" className="underline hover:text-slate-600">
                                Sign up
                            </Link>{" "}
                            for unlimited access.
                        </p>
                    </div>
                </div>

                <p className="text-center text-xs text-slate-400">
                    &copy; 2026 Zhang Lab · CPTAC · LinkedOmics · NCBI PubMed
                </p>
            </div>
        </div>
    )
}
