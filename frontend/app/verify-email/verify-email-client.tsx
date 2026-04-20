"use client"

import { FormEvent, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { authAPI } from "@/lib/auth"

export default function VerifyEmailClient() {
    const searchParams = useSearchParams()
    const router = useRouter()
    const token = searchParams.get("token") || ""
    const [email, setEmail] = useState(searchParams.get("email") || "")
    const [message, setMessage] = useState(
        token
            ? "Verifying your email..."
            : "Check your inbox for a verification link. You need to confirm your email before signing in."
    )
    const [error, setError] = useState("")
    const [loading, setLoading] = useState(Boolean(token))
    const [resendLoading, setResendLoading] = useState(false)
    const [verified, setVerified] = useState(false)

    useEffect(() => {
        if (!token) return

        let cancelled = false
        setLoading(true)
        setError("")

        authAPI
            .verifyEmail(token)
            .then((response) => {
                if (cancelled) return
                setVerified(true)
                setMessage(response.message)
                if (response.email) setEmail(response.email)
            })
            .catch((err: any) => {
                if (cancelled) return
                setError(err.response?.data?.detail || "Could not verify your email. The link may be invalid or expired.")
            })
            .finally(() => {
                if (!cancelled) setLoading(false)
            })

        return () => {
            cancelled = true
        }
    }, [token])

    const handleResend = async (e: FormEvent) => {
        e.preventDefault()
        setError("")
        setResendLoading(true)

        try {
            const response = await authAPI.resendVerification(email)
            setMessage(response.message)
        } catch (err: any) {
            setError(err.response?.data?.detail || "Could not resend the verification email right now.")
        } finally {
            setResendLoading(false)
        }
    }

    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
            <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white/90 shadow-sm px-6 py-7 space-y-5">
                <div className="text-center space-y-2">
                    <Link href="/welcome" className="inline-flex flex-col items-center gap-2 hover:opacity-80 transition-opacity">
                        <img src="/logo.png" alt="LinkedOmicsChat" className="h-12 w-auto" />
                        <span className="text-slate-800 text-3xl font-bold tracking-tight">
                            LinkedOmics<span className="text-teal-600">Chat</span>
                        </span>
                    </Link>
                    <p className="text-slate-500 text-sm">
                        {token ? "Email verification" : "Confirm your email"}
                    </p>
                </div>

                {loading && (
                    <div className="px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-600 text-sm">
                        Verifying your email...
                    </div>
                )}

                {!loading && message && (
                    <div className="px-3 py-2.5 rounded-xl bg-teal-50 border border-teal-200 text-teal-700 text-sm">
                        {message}
                    </div>
                )}

                {error && (
                    <div className="px-3 py-2.5 rounded-xl bg-red-50 border border-red-200 text-red-600 text-sm">
                        {error}
                    </div>
                )}

                {verified ? (
                    <div className="space-y-3">
                        <button
                            type="button"
                            onClick={() => router.push("/login")}
                            className="w-full py-2.5 px-4 rounded-xl bg-teal-600 hover:bg-teal-700 text-white font-medium text-sm transition-all shadow-sm shadow-teal-200"
                        >
                            Go to Sign In
                        </button>
                    </div>
                ) : (
                    <form onSubmit={handleResend} className="space-y-4">
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
                                className="w-full px-3.5 py-2.5 rounded-xl text-sm border border-slate-200 bg-white text-slate-700"
                            />
                        </div>

                        <button
                            type="submit"
                            disabled={resendLoading || !email}
                            className="w-full py-2.5 px-4 rounded-xl border border-slate-200 text-slate-700 hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium transition-all"
                        >
                            {resendLoading ? "Sending..." : "Resend verification email"}
                        </button>
                    </form>
                )}

                <div className="text-center text-sm text-slate-500 space-y-2">
                    <div>
                        <Link href="/login" className="text-teal-600 hover:text-teal-700 hover:underline font-medium">
                            Back to Sign In
                        </Link>
                    </div>
                    <div>
                        <Link href="/register" className="hover:text-slate-700 hover:underline">
                            Create a different account
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    )
}
