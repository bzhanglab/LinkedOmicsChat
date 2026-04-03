"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import {
    Activity,
    ArrowLeft,
    MessageSquareText,
    RefreshCw,
    Shield,
    ThumbsDown,
    ThumbsUp,
    Users,
} from "lucide-react"

import { useAuth } from "@/components/AuthContext"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
    adminAPI,
    type AdminDashboardResponse,
    type AdminFeedbackItem,
    type AdminRecentTurn,
} from "@/lib/api"

function formatNumber(value: number): string {
    return new Intl.NumberFormat().format(value)
}

function formatTimestamp(timestamp?: number | null): string {
    if (!timestamp) return "N/A"
    return new Date(timestamp * 1000).toLocaleString()
}

function confidenceLabel(confidence?: string | null): string {
    if (!confidence) return "Unscored"
    if (confidence === "general_knowledge") return "General knowledge"
    return confidence.charAt(0).toUpperCase() + confidence.slice(1)
}

function FeedbackBadge({ rating }: { rating: 1 | -1 }) {
    const positive = rating === 1
    return (
        <span className={positive ? "inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300" : "inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700 dark:bg-rose-950/30 dark:text-rose-300"}>
            {positive ? <ThumbsUp className="h-3 w-3" /> : <ThumbsDown className="h-3 w-3" />}
            {positive ? "Helpful" : "Not helpful"}
        </span>
    )
}

function ConfidenceBadge({ confidence }: { confidence?: string | null }) {
    const normalized = confidence || "unknown"
    const className =
        normalized === "high"
            ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300"
            : normalized === "partial"
            ? "bg-sky-50 text-sky-700 dark:bg-sky-950/30 dark:text-sky-300"
            : normalized === "low"
            ? "bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300"
            : "bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300"

    return (
        <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${className}`}>
            {confidenceLabel(confidence)}
        </span>
    )
}

function MetricCard({
    label,
    value,
    hint,
    icon: Icon,
}: {
    label: string
    value: string
    hint: string
    icon: typeof Activity
}) {
    return (
        <Card className="border-slate-200/80 bg-white/85 shadow-sm dark:border-slate-800 dark:bg-slate-950/70">
            <CardContent className="p-5">
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <p className="text-sm font-medium text-slate-600 dark:text-slate-400">{label}</p>
                        <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 dark:text-white">{value}</p>
                        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{hint}</p>
                    </div>
                    <div className="rounded-2xl bg-teal-50 p-2.5 text-teal-700 dark:bg-teal-950/40 dark:text-teal-300">
                        <Icon className="h-5 w-5" />
                    </div>
                </div>
            </CardContent>
        </Card>
    )
}

function FeedbackRow({ item }: { item: AdminFeedbackItem }) {
    return (
        <tr className="border-t border-slate-200/70 dark:border-slate-800">
            <td className="px-4 py-3 align-top">
                <FeedbackBadge rating={item.rating} />
            </td>
            <td className="px-4 py-3 align-top">
                <div className="font-medium text-slate-900 dark:text-slate-100">{item.query_preview}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{item.message_preview || "No preview available"}</div>
            </td>
            <td className="px-4 py-3 align-top text-xs text-slate-500 dark:text-slate-400">
                <div>{item.username || "Unknown user"}</div>
                <div>{formatTimestamp(item.timestamp)}</div>
            </td>
        </tr>
    )
}

function RecentTurnRow({ item }: { item: AdminRecentTurn }) {
    return (
        <tr className="border-t border-slate-200/70 dark:border-slate-800">
            <td className="px-4 py-3 align-top">
                <ConfidenceBadge confidence={item.confidence} />
            </td>
            <td className="px-4 py-3 align-top">
                <div className="font-medium text-slate-900 dark:text-slate-100">{item.query_preview}</div>
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{item.message_preview || "No preview available"}</div>
            </td>
            <td className="px-4 py-3 align-top text-xs text-slate-500 dark:text-slate-400">
                <div>{item.username || "Unknown user"}</div>
                <div>{formatTimestamp(item.timestamp)}</div>
            </td>
            <td className="px-4 py-3 align-top text-xs text-slate-500 dark:text-slate-400">
                <div>{item.tools_used.length ? item.tools_used.join(", ") : "No tools"}</div>
                <div className="mt-1">{item.feedback_rating != null ? `Feedback: ${item.feedback_rating === 1 ? "up" : "down"}` : "No feedback yet"}</div>
            </td>
        </tr>
    )
}

export default function AdminPage() {
    const { user, loading, isAuthenticated, isResolvingUser, authError, logout } = useAuth()
    const router = useRouter()
    const [dashboard, setDashboard] = useState<AdminDashboardResponse | null>(null)
    const [pageLoading, setPageLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const loadDashboard = useCallback(async () => {
        setPageLoading(true)
        setError(null)
        try {
            const data = await adminAPI.getDashboard()
            setDashboard(data)
        } catch (err: any) {
            setError(err?.response?.data?.detail || err?.message || "Failed to load admin dashboard")
        } finally {
            setPageLoading(false)
        }
    }, [])

    useEffect(() => {
        if (!loading && !isAuthenticated) {
            router.push("/login")
        }
    }, [isAuthenticated, loading, router])

    useEffect(() => {
        if (!loading && !isResolvingUser && user?.is_admin) {
            void loadDashboard()
        } else if (!loading && !isResolvingUser) {
            setPageLoading(false)
        }
    }, [isResolvingUser, loadDashboard, loading, user])

    if (loading || (isAuthenticated && isResolvingUser) || (pageLoading && !dashboard && !error)) {
        return (
            <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top_left,_rgba(13,148,136,0.14),transparent_30%),linear-gradient(180deg,#f8fafc_0%,#eef6f5_100%)] px-6 dark:bg-[radial-gradient(circle_at_top_left,_rgba(45,212,191,0.12),transparent_30%),linear-gradient(180deg,#020617_0%,#0f172a_100%)]">
                <div className="text-center">
                    <div className="mx-auto h-12 w-12 animate-spin rounded-full border-2 border-slate-300 border-t-teal-600 dark:border-slate-700 dark:border-t-teal-400" />
                    <p className="mt-4 text-sm text-slate-600 dark:text-slate-400">Loading admin dashboard...</p>
                </div>
            </div>
        )
    }

    if (isAuthenticated && !user) {
        return (
            <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top_left,_rgba(13,148,136,0.14),transparent_30%),linear-gradient(180deg,#f8fafc_0%,#eef6f5_100%)] px-6 dark:bg-[radial-gradient(circle_at_top_left,_rgba(45,212,191,0.12),transparent_30%),linear-gradient(180deg,#020617_0%,#0f172a_100%)]">
                <Card className="w-full max-w-lg border-slate-200/80 bg-white/90 dark:border-slate-800 dark:bg-slate-950/80">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-slate-900 dark:text-white">
                            <Shield className="h-5 w-5 text-teal-600 dark:text-teal-400" />
                            Could not verify your session
                        </CardTitle>
                        <CardDescription>
                            {authError || "The app still has an auth token, but the account profile could not be loaded. This often happens right after a backend restart or when /auth/me fails."}
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="flex gap-3">
                        <Button variant="outline" onClick={() => window.location.reload()}>
                            <RefreshCw className="h-4 w-4" />
                            Retry
                        </Button>
                        <Button onClick={logout}>
                            Sign out
                        </Button>
                    </CardContent>
                </Card>
            </div>
        )
    }

    if (!user?.is_admin) {
        return (
            <div className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top_left,_rgba(13,148,136,0.14),transparent_30%),linear-gradient(180deg,#f8fafc_0%,#eef6f5_100%)] px-6 dark:bg-[radial-gradient(circle_at_top_left,_rgba(45,212,191,0.12),transparent_30%),linear-gradient(180deg,#020617_0%,#0f172a_100%)]">
                <Card className="w-full max-w-lg border-slate-200/80 bg-white/90 dark:border-slate-800 dark:bg-slate-950/80">
                    <CardHeader>
                        <CardTitle className="flex items-center gap-2 text-slate-900 dark:text-white">
                            <Shield className="h-5 w-5 text-teal-600 dark:text-teal-400" />
                            Admin access required
                        </CardTitle>
                        <CardDescription>
                            This page is only visible to accounts whose email is listed in the backend <code>ADMIN_EMAILS</code> setting.
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="flex gap-3">
                        <Button asChild variant="outline">
                            <Link href="/">
                                <ArrowLeft className="h-4 w-4" />
                                Back to chat
                            </Link>
                        </Button>
                    </CardContent>
                </Card>
            </div>
        )
    }

    const overview = dashboard?.overview
    const quality = dashboard?.quality_signals

    return (
        <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(13,148,136,0.14),transparent_30%),linear-gradient(180deg,#f8fafc_0%,#eef6f5_100%)] px-4 py-6 dark:bg-[radial-gradient(circle_at_top_left,_rgba(45,212,191,0.12),transparent_30%),linear-gradient(180deg,#020617_0%,#0f172a_100%)] sm:px-6 lg:px-8">
            <div className="mx-auto max-w-7xl space-y-6">
                <div className="rounded-3xl border border-slate-200/80 bg-white/80 p-6 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-950/70">
                    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                        <div>
                            <div className="inline-flex items-center gap-2 rounded-full border border-teal-200 bg-teal-50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-teal-700 dark:border-teal-900 dark:bg-teal-950/40 dark:text-teal-300">
                                <Shield className="h-3.5 w-3.5" />
                                Internal admin
                            </div>
                            <h1 className="mt-4 text-4xl font-semibold tracking-tight text-slate-900 dark:text-white">Operations Dashboard</h1>
                            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-400">
                                Monitor usage, token spend, feedback trends, and recent turns from one place without digging through SQLite tables or ad hoc scripts.
                            </p>
                            <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
                                Generated {formatTimestamp(dashboard?.generated_at)} for {user.email}
                            </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-3">
                            <Button asChild variant="outline">
                                <Link href="/">
                                    <ArrowLeft className="h-4 w-4" />
                                    Back to chat
                                </Link>
                            </Button>
                            <Button variant="default" onClick={() => void loadDashboard()} disabled={pageLoading}>
                                <RefreshCw className={`h-4 w-4 ${pageLoading ? "animate-spin" : ""}`} />
                                Refresh
                            </Button>
                        </div>
                    </div>
                    {error && (
                        <div className="mt-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
                            {error}
                        </div>
                    )}
                </div>

                {overview && quality && (
                    <>
                        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                            <MetricCard label="Total queries" value={formatNumber(overview.total_queries)} hint={`${formatNumber(overview.total_registered_queries)} signed-in + ${formatNumber(overview.total_guest_queries)} guest`} icon={Activity} />
                            <MetricCard label="Token volume" value={formatNumber(overview.total_tokens)} hint={`${formatNumber(overview.total_input_tokens)} input / ${formatNumber(overview.total_output_tokens)} output`} icon={MessageSquareText} />
                            <MetricCard label="Users" value={formatNumber(overview.total_users)} hint={`${formatNumber(overview.active_users)} active accounts`} icon={Users} />
                            <MetricCard label="Sessions" value={formatNumber(overview.total_sessions)} hint={`${formatNumber(overview.total_messages)} saved turns`} icon={Shield} />
                            <MetricCard label="Approval rate" value={`${overview.positive_feedback_rate.toFixed(1)}%`} hint={`${formatNumber(overview.positive_feedback)} up / ${formatNumber(overview.negative_feedback)} down`} icon={ThumbsUp} />
                            <MetricCard label="Quality flags" value={formatNumber(quality.low_confidence_responses + quality.no_data_responses)} hint={`${formatNumber(quality.partial_confidence_responses)} partial and ${formatNumber(quality.general_knowledge_responses)} general knowledge`} icon={ThumbsDown} />
                        </div>

                        <div className="grid gap-6 xl:grid-cols-[1.35fr_0.95fr]">
                            <Card className="border-slate-200/80 bg-white/85 dark:border-slate-800 dark:bg-slate-950/70">
                                <CardHeader>
                                    <CardTitle className="text-slate-900 dark:text-white">Daily activity</CardTitle>
                                    <CardDescription>Last {dashboard.daily_activity.length} days of query volume, token usage, and feedback.</CardDescription>
                                </CardHeader>
                                <CardContent className="overflow-x-auto">
                                    <table className="min-w-full text-sm">
                                        <thead className="text-left text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                                            <tr>
                                                <th className="px-4 pb-3">Date</th>
                                                <th className="px-4 pb-3">Users</th>
                                                <th className="px-4 pb-3">Queries</th>
                                                <th className="px-4 pb-3">Feedback</th>
                                                <th className="px-4 pb-3">Tokens</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {dashboard.daily_activity.map((day) => (
                                                <tr key={day.date} className="border-t border-slate-200/70 dark:border-slate-800">
                                                    <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">{day.date}</td>
                                                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{formatNumber(day.active_users)}</td>
                                                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300">
                                                        {formatNumber(day.registered_queries + day.guest_queries)}
                                                        <div className="text-xs text-slate-400">guest {formatNumber(day.guest_queries)}</div>
                                                    </td>
                                                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{formatNumber(day.feedback_count)}</td>
                                                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{formatNumber(day.input_tokens + day.output_tokens)}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </CardContent>
                            </Card>

                            <div className="grid gap-6">
                                <Card className="border-slate-200/80 bg-white/85 dark:border-slate-800 dark:bg-slate-950/70">
                                    <CardHeader>
                                        <CardTitle className="text-slate-900 dark:text-white">Quality signals</CardTitle>
                                        <CardDescription>Saved-turn counts derived from assistant response metadata.</CardDescription>
                                    </CardHeader>
                                    <CardContent className="grid grid-cols-2 gap-3 text-sm">
                                        <div className="rounded-2xl bg-amber-50 p-4 dark:bg-amber-950/30">
                                            <div className="text-xs uppercase tracking-wide text-amber-700 dark:text-amber-300">Low confidence</div>
                                            <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{formatNumber(quality.low_confidence_responses)}</div>
                                        </div>
                                        <div className="rounded-2xl bg-sky-50 p-4 dark:bg-sky-950/30">
                                            <div className="text-xs uppercase tracking-wide text-sky-700 dark:text-sky-300">Partial confidence</div>
                                            <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{formatNumber(quality.partial_confidence_responses)}</div>
                                        </div>
                                        <div className="rounded-2xl bg-slate-100 p-4 dark:bg-slate-900">
                                            <div className="text-xs uppercase tracking-wide text-slate-700 dark:text-slate-300">General knowledge</div>
                                            <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{formatNumber(quality.general_knowledge_responses)}</div>
                                        </div>
                                        <div className="rounded-2xl bg-rose-50 p-4 dark:bg-rose-950/30">
                                            <div className="text-xs uppercase tracking-wide text-rose-700 dark:text-rose-300">No-data replies</div>
                                            <div className="mt-2 text-2xl font-semibold text-slate-900 dark:text-white">{formatNumber(quality.no_data_responses)}</div>
                                        </div>
                                    </CardContent>
                                </Card>

                                <Card className="border-slate-200/80 bg-white/85 dark:border-slate-800 dark:bg-slate-950/70">
                                    <CardHeader>
                                        <CardTitle className="text-slate-900 dark:text-white">Model usage</CardTitle>
                                        <CardDescription>Most expensive models by total tokens.</CardDescription>
                                    </CardHeader>
                                    <CardContent className="space-y-3">
                                        {dashboard.model_usage.map((item) => (
                                            <div key={item.model} className="rounded-2xl border border-slate-200/70 p-3 dark:border-slate-800">
                                                <div className="flex items-center justify-between gap-3">
                                                    <div className="min-w-0">
                                                        <div className="truncate font-medium text-slate-900 dark:text-slate-100">{item.model}</div>
                                                        <div className="text-xs text-slate-500 dark:text-slate-400">{formatNumber(item.queries)} queries</div>
                                                    </div>
                                                    <div className="text-right text-sm font-semibold text-slate-900 dark:text-slate-100">
                                                        {formatNumber(item.total_tokens)}
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </CardContent>
                                </Card>
                            </div>
                        </div>

                        <div className="grid gap-6 xl:grid-cols-2">
                            <Card className="border-slate-200/80 bg-white/85 dark:border-slate-800 dark:bg-slate-950/70">
                                <CardHeader>
                                    <CardTitle className="text-slate-900 dark:text-white">Top users</CardTitle>
                                    <CardDescription>Ranked by total token usage across saved conversations.</CardDescription>
                                </CardHeader>
                                <CardContent className="overflow-x-auto">
                                    <table className="min-w-full text-sm">
                                        <thead className="text-left text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                                            <tr>
                                                <th className="px-4 pb-3">User</th>
                                                <th className="px-4 pb-3">Queries</th>
                                                <th className="px-4 pb-3">Tokens</th>
                                                <th className="px-4 pb-3">Last seen</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {dashboard.top_users.map((item) => (
                                                <tr key={item.user_id} className="border-t border-slate-200/70 dark:border-slate-800">
                                                    <td className="px-4 py-3">
                                                        <div className="font-medium text-slate-900 dark:text-slate-100">{item.username}</div>
                                                        <div className="text-xs text-slate-500 dark:text-slate-400">{item.email}</div>
                                                    </td>
                                                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300">
                                                        {formatNumber(item.queries)}
                                                        <div className="text-xs text-slate-400">{formatNumber(item.sessions)} sessions</div>
                                                    </td>
                                                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{formatNumber(item.total_tokens)}</td>
                                                    <td className="px-4 py-3 text-slate-600 dark:text-slate-300">{formatTimestamp(item.last_seen_at)}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </CardContent>
                            </Card>

                            <Card className="border-slate-200/80 bg-white/85 dark:border-slate-800 dark:bg-slate-950/70">
                                <CardHeader>
                                    <CardTitle className="text-slate-900 dark:text-white">Feedback hotspots</CardTitle>
                                    <CardDescription>Queries attracting the most negative feedback.</CardDescription>
                                </CardHeader>
                                <CardContent className="space-y-3">
                                    {dashboard.top_feedback_targets.map((item) => (
                                        <div key={item.query} className="rounded-2xl border border-slate-200/70 p-4 dark:border-slate-800">
                                            <div className="font-medium text-slate-900 dark:text-slate-100">{item.query}</div>
                                            <div className="mt-2 flex flex-wrap gap-2 text-xs">
                                                <span className="rounded-full bg-rose-50 px-2 py-1 font-medium text-rose-700 dark:bg-rose-950/30 dark:text-rose-300">
                                                    {formatNumber(item.negative_count)} down
                                                </span>
                                                <span className="rounded-full bg-emerald-50 px-2 py-1 font-medium text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
                                                    {formatNumber(item.positive_count)} up
                                                </span>
                                                <span className="rounded-full bg-slate-100 px-2 py-1 font-medium text-slate-700 dark:bg-slate-900 dark:text-slate-300">
                                                    {formatNumber(item.total_count)} total
                                                </span>
                                            </div>
                                        </div>
                                    ))}
                                </CardContent>
                            </Card>
                        </div>

                        <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
                            <Card className="border-slate-200/80 bg-white/85 dark:border-slate-800 dark:bg-slate-950/70">
                                <CardHeader>
                                    <CardTitle className="text-slate-900 dark:text-white">Tool usage</CardTitle>
                                    <CardDescription>Most frequently used tool families in saved turns.</CardDescription>
                                </CardHeader>
                                <CardContent className="space-y-3">
                                    {dashboard.tool_usage.map((item) => (
                                        <div key={item.tool} className="flex items-center justify-between gap-3 rounded-2xl border border-slate-200/70 p-3 dark:border-slate-800">
                                            <div className="font-medium text-slate-900 dark:text-slate-100">{item.tool}</div>
                                            <div className="text-sm text-slate-600 dark:text-slate-300">{formatNumber(item.count)}</div>
                                        </div>
                                    ))}
                                </CardContent>
                            </Card>

                            <Card className="border-slate-200/80 bg-white/85 dark:border-slate-800 dark:bg-slate-950/70">
                                <CardHeader>
                                    <CardTitle className="text-slate-900 dark:text-white">Recent feedback</CardTitle>
                                    <CardDescription>Most recent thumbs-up and thumbs-down events attached to assistant turns.</CardDescription>
                                </CardHeader>
                                <CardContent className="overflow-x-auto">
                                    <table className="min-w-full text-sm">
                                        <thead className="text-left text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                                            <tr>
                                                <th className="px-4 pb-3">Signal</th>
                                                <th className="px-4 pb-3">Turn</th>
                                                <th className="px-4 pb-3">User</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {dashboard.recent_feedback.map((item) => (
                                                <FeedbackRow key={item.id} item={item} />
                                            ))}
                                        </tbody>
                                    </table>
                                </CardContent>
                            </Card>
                        </div>

                        <Card className="border-slate-200/80 bg-white/85 dark:border-slate-800 dark:bg-slate-950/70">
                            <CardHeader>
                                <CardTitle className="text-slate-900 dark:text-white">Recent turns</CardTitle>
                                <CardDescription>Latest saved turns with confidence, tool usage, and latest feedback signal.</CardDescription>
                            </CardHeader>
                            <CardContent className="overflow-x-auto">
                                <table className="min-w-full text-sm">
                                    <thead className="text-left text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                                        <tr>
                                            <th className="px-4 pb-3">Confidence</th>
                                            <th className="px-4 pb-3">Turn</th>
                                            <th className="px-4 pb-3">User</th>
                                            <th className="px-4 pb-3">Tools / feedback</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {dashboard.recent_turns.map((item) => (
                                            <RecentTurnRow key={item.turn_id} item={item} />
                                        ))}
                                    </tbody>
                                </table>
                            </CardContent>
                        </Card>
                    </>
                )}
            </div>
        </div>
    )
}
