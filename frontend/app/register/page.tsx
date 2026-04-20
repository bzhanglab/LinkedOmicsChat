"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { useAuth } from "@/components/AuthContext"

export default function RegisterPage() {
    const [username, setUsername] = useState("")
    const [email, setEmail] = useState("")
    const [password, setPassword] = useState("")
    const [confirmPassword, setConfirmPassword] = useState("")
    const [error, setError] = useState("")
    const [info, setInfo] = useState("")
    const [loading, setLoading] = useState(false)
    const { register, user, loading: authLoading } = useAuth()
    const router = useRouter()

    useEffect(() => {
        if (!authLoading && user) {
            router.push("/")
        }
    }, [authLoading, user, router])

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError("")
        setInfo("")

        if (password.length < 8) {
            setError("Password must be at least 8 characters long")
            return
        }

        if (password !== confirmPassword) {
            setError("Passwords do not match")
            return
        }

        setLoading(true)

        try {
            const response = await register(username, email, password)
            if (response.requires_email_verification) {
                router.push(`/verify-email?email=${encodeURIComponent(response.email)}`)
                return
            }
            setInfo(response.message)
            router.push("/")
        } catch (err: any) {
            setError(err.message || "Registration failed. Please try again.")
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="min-h-screen flex flex-col items-center justify-center relative overflow-hidden bg-slate-50">

            <div className="relative z-10 w-full max-w-md px-4 py-12 flex flex-col gap-8">

                {/* Brand */}
                <div className="text-center space-y-1">
                    <Link href="/welcome" className="inline-flex flex-col items-center gap-2 hover:opacity-80 transition-opacity">
                        <img src="/logo.png" alt="LinkedOmicsChat" className="h-12 w-auto" />
                        <span className="text-slate-800 text-4xl font-bold tracking-tight">LinkedOmics<span className="text-teal-600">Chat</span></span>
                    </Link>
                    <p className="text-slate-500 text-sm">Create your account</p>
                </div>

                {/* Glass card */}
                <div className="glass-card-light rounded-3xl px-6 py-7 space-y-5">

                    {error && (
                        <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-red-50 border border-red-200 text-red-600 text-sm">
                            {error}
                        </div>
                    )}

                    {info && (
                        <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-teal-50 border border-teal-200 text-teal-700 text-sm">
                            {info}
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
                                minLength={3}
                                maxLength={50}
                                placeholder="Choose a username (3-50 characters)"
                                autoComplete="username"
                                className="glass-input-light w-full px-3.5 py-2.5 rounded-xl text-sm transition-all"
                            />
                        </div>

                        <div>
                            <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1.5">
                                Email
                            </label>
                            <input
                                id="email"
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                placeholder="Enter your email"
                                autoComplete="email"
                                className="glass-input-light w-full px-3.5 py-2.5 rounded-xl text-sm transition-all"
                            />
                        </div>

                        <div>
                            <label htmlFor="password" className="block text-sm font-medium text-slate-700 mb-1.5">
                                Password
                            </label>
                            <input
                                id="password"
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                minLength={8}
                                placeholder="Enter password (min 8 characters)"
                                autoComplete="new-password"
                                className="glass-input-light w-full px-3.5 py-2.5 rounded-xl text-sm transition-all"
                            />
                        </div>

                        <div>
                            <label htmlFor="confirmPassword" className="block text-sm font-medium text-slate-700 mb-1.5">
                                Confirm Password
                            </label>
                            <input
                                id="confirmPassword"
                                type="password"
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                required
                                placeholder="Confirm your password"
                                autoComplete="new-password"
                                className="glass-input-light w-full px-3.5 py-2.5 rounded-xl text-sm transition-all"
                            />
                        </div>

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full py-2.5 px-4 rounded-xl bg-teal-600 hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium text-sm transition-all shadow-sm shadow-teal-200"
                        >
                            {loading ? "Creating account..." : "Sign up"}
                        </button>
                    </form>

                    <p className="text-center text-sm text-slate-500">
                        Already have an account?{" "}
                        <Link href="/login" className="text-teal-600 hover:text-teal-700 hover:underline font-medium">
                            Sign in
                        </Link>
                    </p>
                </div>

                <p className="text-center text-xs text-slate-400">
                    &copy; 2026 Zhang Lab · CPTAC · LinkedOmics · NCBI PubMed
                </p>
            </div>
        </div>
    )
}
