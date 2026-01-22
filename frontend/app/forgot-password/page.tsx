"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import Link from "next/link"
import { authAPI } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function ForgotPasswordPage() {
    const [username, setUsername] = useState("")
    const [email, setEmail] = useState("")
    const [error, setError] = useState("")
    const [loading, setLoading] = useState(false)
    const [resetToken, setResetToken] = useState<string | null>(null)
    const router = useRouter()

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError("")
        setLoading(true)

        try {
            const response = await authAPI.forgotPassword({ username, email })
            if (response.reset_token) {
                setResetToken(response.reset_token)
            } else {
                setError("Username and email do not match any account.")
            }
        } catch (err: any) {
            setError(err.response?.data?.detail || "Failed to generate reset token. Please check your username and email.")
        } finally {
            setLoading(false)
        }
    }

    if (resetToken) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-background px-4">
                <Card className="w-full max-w-md">
                    <CardHeader>
                        <CardTitle>Password Reset Token</CardTitle>
                        <CardDescription>
                            ⚠️ SECURITY WARNING: Anyone with this token can reset the password.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                        <div className="p-4 bg-destructive/10 border border-destructive/20 rounded-md">
                            <p className="text-xs text-destructive font-semibold mb-2">
                                ⚠️ Keep this token secure! Anyone who has it can reset the password.
                            </p>
                            <p className="text-sm font-mono break-all text-center bg-background p-2 rounded border">
                                {resetToken}
                            </p>
                        </div>
                        <p className="text-sm text-muted-foreground text-center">
                            This token expires in 1 hour.
                        </p>
                        <p className="text-xs text-muted-foreground text-center italic">
                            Note: This is a development-only feature. In production, tokens should be sent via email.
                        </p>
                        <div className="flex gap-2">
                            <Button
                                onClick={() => {
                                    navigator.clipboard.writeText(resetToken)
                                    alert("Token copied to clipboard!")
                                }}
                                className="flex-1"
                                variant="outline"
                            >
                                Copy Token
                            </Button>
                            <Button
                                onClick={() => router.push("/reset-password")}
                                className="flex-1"
                            >
                                Reset Password
                            </Button>
                        </div>
                        <div className="text-center text-sm">
                            <Link href="/login" className="text-primary hover:underline">
                                Back to Login
                            </Link>
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
                    <CardTitle>Forgot Password</CardTitle>
                    <CardDescription>
                        Enter your username and email to receive a password reset token
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
                            <label htmlFor="email" className="block text-sm font-medium mb-2">
                                Email
                            </label>
                            <Input
                                id="email"
                                type="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                placeholder="Enter your email"
                                autoComplete="email"
                            />
                        </div>

                        <Button
                            type="submit"
                            className="w-full"
                            disabled={loading}
                        >
                            {loading ? "Generating token..." : "Get Reset Token"}
                        </Button>
                    </form>

                    <div className="mt-4 text-center text-sm">
                        <Link href="/login" className="text-primary hover:underline">
                            Back to Login
                        </Link>
                    </div>
                </CardContent>
            </Card>
        </div>
    )
}
