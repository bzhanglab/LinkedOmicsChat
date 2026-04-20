import { Suspense } from "react"
import VerifyEmailClient from "./verify-email-client"

function VerifyEmailFallback() {
    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
            <div className="w-full max-w-md rounded-3xl border border-slate-200 bg-white/90 shadow-sm px-6 py-7">
                <div className="px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-200 text-slate-600 text-sm">
                    Loading verification...
                </div>
            </div>
        </div>
    )
}

export default function VerifyEmailPage() {
    return (
        <Suspense fallback={<VerifyEmailFallback />}>
            <VerifyEmailClient />
        </Suspense>
    )
}
