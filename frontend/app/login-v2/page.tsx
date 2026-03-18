"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import Image from "next/image"
import { useAuth } from "@/components/AuthContext"

const features = [
    { icon: "🧬", label: "CPTAC proteomics" },
    { icon: "🔗", label: "LinkedOmics networks" },
    { icon: "📄", label: "PubMed literature" },
]

export default function LoginPageV2() {
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
        <div className="min-h-screen flex flex-col bg-slate-50 dark:bg-gray-950">

            {/* ── Hero band ── */}
            <div className="bg-gradient-to-br from-slate-900 via-teal-950 to-slate-900 px-6 py-10 flex flex-col items-center text-center gap-5">
                <div className="flex items-center gap-3">
                    <Image
                        src="/logo.png"
                        alt="LinkedOmicsChat"
                        width={40}
                        height={40}
                        className="h-10 w-10 object-contain"
                    />
                    <span className="text-white text-xl font-bold tracking-tight">LinkedOmicsChat</span>
                </div>

                <div>
                    <h1 className="text-white text-2xl sm:text-3xl font-bold leading-snug">
                        Ask questions about cancer omics.<br />
                        <span className="text-teal-400">Get answers instantly.</span>
                    </h1>
                    <p className="mt-2 text-slate-400 text-sm max-w-xs mx-auto">
                        Natural language interface to TCGA, CPTAC, and biomedical literature.
                    </p>
                </div>

                {/* Feature chips */}
                <div className="flex flex-wrap justify-center gap-2">
                    {features.map((f) => (
                        <span
                            key={f.label}
                            className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-white/15 text-white text-xs font-medium backdrop-blur-sm border border-white/20"
                        >
                            {f.icon} {f.label}
                        </span>
                    ))}
                </div>
            </div>

            {/* ── Form card ── */}
            <div className="flex-1 flex flex-col items-center px-4 -mt-5">
                <div className="w-full max-w-sm bg-white dark:bg-gray-900 rounded-2xl shadow-xl border border-slate-200 dark:border-gray-800 px-6 py-7 space-y-5">

                    <div>
                        <h2 className="text-gray-900 dark:text-white text-lg font-semibold">Sign in to your account</h2>
                    </div>

                    {error && (
                        <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 text-sm">
                            <svg className="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                            </svg>
                            {error}
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div>
                            <label htmlFor="username" className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
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
                                className="w-full px-3.5 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition"
                            />
                        </div>

                        <div>
                            <div className="flex items-center justify-between mb-1.5">
                                <label htmlFor="password" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
                                    Password
                                </label>
                                <Link href="/forgot-password" className="text-xs text-teal-600 dark:text-teal-400 hover:underline">
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
                                className="w-full px-3.5 py-2.5 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition"
                            />
                        </div>

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full py-2.5 px-4 rounded-lg bg-teal-600 hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium text-sm transition-colors"
                        >
                            {loading ? "Signing in…" : "Sign in"}
                        </button>
                    </form>

                    <p className="text-center text-sm text-gray-500 dark:text-gray-400">
                        No account?{" "}
                        <Link href="/register" className="text-teal-600 dark:text-teal-400 hover:underline font-medium">
                            Sign up
                        </Link>
                    </p>

                    <div className="relative">
                        <div className="absolute inset-0 flex items-center">
                            <div className="w-full border-t border-gray-200 dark:border-gray-700" />
                        </div>
                        <div className="relative flex justify-center">
                            <span className="bg-white dark:bg-gray-900 px-3 text-xs text-gray-400">or</span>
                        </div>
                    </div>

                    <div className="space-y-2">
                        <button
                            type="button"
                            onClick={handleGuestMode}
                            className="w-full py-2.5 px-4 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 text-sm font-medium transition-colors"
                        >
                            Continue as Guest
                        </button>
                        <p className="text-center text-xs text-gray-400 dark:text-gray-500 leading-relaxed">
                            Guest access is rate-limited and sessions are not saved.{" "}
                            <Link href="/register" className="underline hover:text-gray-600 dark:hover:text-gray-300">
                                Sign up
                            </Link>{" "}
                            for unlimited access.
                        </p>
                    </div>
                </div>
            </div>

            <p className="text-center text-xs text-gray-400 dark:text-gray-600 py-6">
                Data: CPTAC · LinkedOmics · NCBI PubMed
            </p>
        </div>
    )
}
