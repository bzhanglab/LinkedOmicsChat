"use client"

import { useEffect } from "react"
import { Button } from "@/components/ui/button"

export default function Error({
    error,
    reset,
}: {
    error: Error & { digest?: string }
    reset: () => void
}) {
    useEffect(() => {
        console.error("Application error:", error)
    }, [error])

    return (
        <div className="flex h-screen items-center justify-center bg-background">
            <div className="text-center space-y-4 max-w-md">
                <h2 className="text-2xl font-semibold">Something went wrong!</h2>
                <p className="text-muted-foreground">
                    {error.message || "An unexpected error occurred"}
                </p>
                <Button onClick={reset}>Try again</Button>
            </div>
        </div>
    )
}
