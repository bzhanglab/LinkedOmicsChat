"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { authAPI } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function ResetPasswordPage() {
    const [token, setToken] = useState("")
    const [password, setPassword] = useState("")
    const [confirmPassword, setConfirmPassword] = useState("")
    const [error, setError] = useState("")
    const [success, setSuccess] = useState(false)
    const [loading, setLoading] = useState(false)
    const router = useRouter()

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError("")

        // Validation
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
            await authAPI.resetPassword({ token, new_password: password })
            setSuccess(true)
            // Redirect to login after 2 seconds
            setTimeout(() => {
                router.push("/login")
            }, 2000)
        } catch (err: any) {
            setError(err.response?.data?.detail || "Failed to reset password. Please check your token.")
        } finally {
            setLoading(false)
        }
    }

    if (success) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-background px-4">
                <Card className="w-full max-w-md">
                    <CardHeader>
                        <CardTitle>Password Reset Successful</CardTitle>
                        <CardDescription>
                            Your password has been reset. Redirecting to login...
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        <div className="text-center">
                            <Button onClick={() => router.push("/login")} className="w-full">
                                Go to Login
                            </Button>
                        </div>
                    </CardContent>
                </Card>
            </div>
        )
    }

    return (
        <div className="min-h-screen flex items-center justify-center bg-background px-4">
            <Card className="w-full max-w-md">
                <CardHeader>
                    <CardTitle>Reset Password</CardTitle>
                    <CardDescription>
                        Enter your reset token and new password
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <form onSubmit={handleSubmit} className="space-y-4">
                        {error && (
                            <div className="p-3 rounded-md bg-destructive/10 text-destructive text-sm">
                                {error}
                            </div>
                        )}

                        <div>
                            <label htmlFor="token" className="block text-sm font-medium mb-2">
                                Reset Token
                            </label>
                            <Input
                                id="token"
                                type="text"
                                value={token}
                                onChange={(e) => setToken(e.target.value)}
                                required
                                placeholder="Paste your reset token here"
                            />
                        </div>

                        <div>
                            <label htmlFor="password" className="block text-sm font-medium mb-2">
                                New Password
                            </label>
                            <Input
                                id="password"
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                minLength={8}
                                placeholder="Enter new password (min 8 characters)"
                                autoComplete="new-password"
                            />
                        </div>

                        <div>
                            <label htmlFor="confirmPassword" className="block text-sm font-medium mb-2">
                                Confirm Password
                            </label>
                            <Input
                                id="confirmPassword"
                                type="password"
                                value={confirmPassword}
                                onChange={(e) => setConfirmPassword(e.target.value)}
                                required
                                placeholder="Confirm your new password"
                                autoComplete="new-password"
                            />
                        </div>

                        <Button
                            type="submit"
                            className="w-full"
                            disabled={loading}
                        >
                            {loading ? "Resetting password..." : "Reset Password"}
                        </Button>
                    </form>

                    <div className="mt-4 text-center text-sm space-y-2">
                        <div>
                            <Link href="/forgot-password" className="text-primary hover:underline">
                                Get a new reset token
                            </Link>
                        </div>
                        <div>
                            <Link href="/login" className="text-primary hover:underline">
                                Back to Login
                            </Link>
                        </div>
                    </div>
                </CardContent>
            </Card>
        </div>
    )
}
