"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { useAuth } from "@/components/AuthContext"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

export default function LoginPage() {
    const [username, setUsername] = useState("")
    const [password, setPassword] = useState("")
    const [error, setError] = useState("")
    const [loading, setLoading] = useState(false)
    const { login, isAuthenticated } = useAuth()
    const router = useRouter()

    // Redirect if already authenticated
    if (isAuthenticated) {
        router.push("/")
        return null
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
        <div className="min-h-screen flex items-center justify-center bg-background px-4">
            <div className="w-full max-w-md space-y-8">
                <div className="text-center">
                    <h1 className="text-3xl font-bold">cpgAgent</h1>
                    <p className="mt-2 text-muted-foreground">Sign in to your account</p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-6">
                    {error && (
                        <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm">
                            {error}
                        </div>
                    )}

                    <div className="space-y-4">
                        <div>
                            <label htmlFor="username" className="block text-sm font-medium mb-2">
                                Username
                            </label>
                            <Input
                                id="username"
                                type="text"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                required
                                placeholder="Enter your username"
                                autoComplete="username"
                            />
                        </div>

                        <div>
                            <label htmlFor="password" className="block text-sm font-medium mb-2">
                                Password
                            </label>
                            <Input
                                id="password"
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                placeholder="Enter your password"
                                autoComplete="current-password"
                            />
                        </div>
                    </div>

                    <Button
                        type="submit"
                        className="w-full"
                        disabled={loading}
                    >
                        {loading ? "Signing in..." : "Sign in"}
                    </Button>
                </form>

                <div className="text-center text-sm space-y-2">
                    <div>
                        <span className="text-muted-foreground">Don't have an account? </span>
                        <Link href="/register" className="text-primary hover:underline">
                            Sign up
                        </Link>
                    </div>
                    <div>
                        <Link href="/forgot-password" className="text-primary hover:underline">
                            Forgot password?
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    )
}
