"use client"

import { useState, useEffect, useCallback, useRef, startTransition } from "react"
import { useRouter } from "next/navigation"
import { ChevronLeft, ChevronRight, X, Menu } from "lucide-react"
import { Sidebar } from "@/components/Sidebar"
import { ChatInterface } from "@/components/ChatInterface"
import { UseCasesPanel } from "@/components/UseCasesPanel"
import ToolExplorer from "@/components/ToolExplorer"
import { RightPanel, type RightPanelContext } from "@/components/RightPanel"
import { useAuth } from "@/components/AuthContext"
import { chatAPI } from "@/lib/api"

type View = "chat" | "tools" | "usecases"
const CURRENT_SESSION_KEY = "linkedomicsai-current-session"

interface SearchJumpTarget {
    sessionId: string
    messageId: number
    requestKey: string
}

export default function Home() {
    const { isAuthenticated, isGuest, loading } = useAuth()
    const router = useRouter()

    // All hooks must be declared before any conditional returns
    const [currentView, setCurrentView] = useState<View>(() => {
        if (typeof window !== "undefined") {
            const v = new URLSearchParams(window.location.search).get("view")
            if (v === "tools" || v === "usecases") return v
        }
        return "chat"
    })
    const [prefilledQuery, setPrefilledQuery] = useState<string | null>(null)
    const [rightPanelContext, setRightPanelContext] = useState<RightPanelContext | null>(null)
    const [rightPanelOpen, setRightPanelOpen] = useState(false)
    const [guestBannerDismissed, setGuestBannerDismissed] = useState(false)
    const [mobileNavOpen, setMobileNavOpen] = useState(false)
    const [pendingSearchTarget, setPendingSearchTarget] = useState<SearchJumpTarget | null>(null)
    const [toolsResetKey, setToolsResetKey] = useState(0)
    const [chatFocusKey, setChatFocusKey] = useState(0)
    const [mountedViews, setMountedViews] = useState<Record<View, boolean>>(() => {
        const initialView = typeof window !== "undefined"
            ? (new URLSearchParams(window.location.search).get("view") as View | null)
            : null
        return {
            chat: true,
            tools: initialView === "tools",
            usecases: initialView === "usecases",
        }
    })
    const hasVerifiedRestoredSessionRef = useRef(false)
    // Initialize sessionId from localStorage synchronously to prevent flash
    const [sessionId, setSessionId] = useState<string | null>(() => {
        if (typeof window !== "undefined") {
            const guestMode = sessionStorage.getItem("linkedomicsai-guest-mode") === "true"
            return guestMode ? null : localStorage.getItem(CURRENT_SESSION_KEY)
        }
        return null
    })

    // Redirect to welcome page if not authenticated
    useEffect(() => {
        if (!loading && !isAuthenticated) {
            router.push("/welcome")
        }
    }, [isAuthenticated, loading, router])

    // Pick up prefill query — from URL ?q= param (new tab) or sessionStorage (same tab)
    useEffect(() => {
        if (!isAuthenticated) return
        const urlQuery = new URLSearchParams(window.location.search).get("q")
        if (urlQuery) {
            setPrefilledQuery(urlQuery)
            const url = new URL(window.location.href)
            url.searchParams.delete("q")
            window.history.replaceState({}, "", url.toString())
            return
        }
        const prefill = sessionStorage.getItem("linkedomicsai-prefill-query")
        if (prefill) {
            sessionStorage.removeItem("linkedomicsai-prefill-query")
            setPrefilledQuery(prefill)
        }
    }, [isAuthenticated])

    // Verify the restored session only once after mount.
    // Re-checking on every chat switch adds an extra history request to each selection.
    useEffect(() => {
        if (!isAuthenticated || isGuest) return // Guests do not have persistent history
        if (hasVerifiedRestoredSessionRef.current) return

        const savedSessionId = localStorage.getItem(CURRENT_SESSION_KEY)
        if (savedSessionId && savedSessionId === sessionId) {
            hasVerifiedRestoredSessionRef.current = true
            // Only verify if this is the session we loaded from localStorage.
            // IMPORTANT: don't load the full history here (can be huge). Just fetch a tiny page.
            chatAPI
                .getSessionHistory(savedSessionId, { limit: 1 })
                .catch((err) => {
                    // Only clear if it's truly missing; otherwise ignore transient errors.
                    const status = (err as any)?.response?.status
                    if (status === 404) {
                        setSessionId(null)
                        localStorage.removeItem(CURRENT_SESSION_KEY)
                    }
                })
        } else {
            hasVerifiedRestoredSessionRef.current = true
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isAuthenticated, isGuest, sessionId]) // Session restore is only relevant for signed-in users

    // Save sessionId to localStorage whenever it changes
    useEffect(() => {
        if (!isAuthenticated) return // Don't save if not authenticated

        if (isGuest) {
            localStorage.removeItem(CURRENT_SESSION_KEY)
            return
        }

        if (sessionId) {
            localStorage.setItem(CURRENT_SESSION_KEY, sessionId)
        } else {
            localStorage.removeItem(CURRENT_SESSION_KEY)
        }
    }, [sessionId, isAuthenticated, isGuest])

    const toggleRightPanel = useCallback(() => {
        setRightPanelOpen((v) => !v)
    }, [])

    const handleViewChange = useCallback((view: View) => {
        if (view === "tools") setToolsResetKey((k) => k + 1)
        if (view === "chat") setChatFocusKey((k) => k + 1)
        // Sync URL so the view is bookmarkable / openable in a new tab
        const url = new URL(window.location.href)
        if (view === "chat") {
            url.searchParams.delete("view")
        } else {
            url.searchParams.set("view", view)
        }
        window.history.replaceState({}, "", url.toString())
        startTransition(() => {
            setCurrentView(view)
            setMountedViews((prev) => (prev[view] ? prev : { ...prev, [view]: true }))
        })
    }, [])

    const handleSessionChange = useCallback((id: string | null) => {
        setPendingSearchTarget(null)
        setRightPanelContext(null)
        setSessionId(id)
    }, [])

    const handleSearchResultSelect = useCallback((target: { sessionId: string; messageId: number }) => {
        setPendingSearchTarget({
            ...target,
            requestKey: `${target.sessionId}:${target.messageId}:${Date.now()}`,
        })
        setSessionId(target.sessionId)
        startTransition(() => setCurrentView("chat"))
    }, [])

    const handleContextUpdate = useCallback((ctx: RightPanelContext) => {
        setRightPanelContext(ctx)
    }, [])

    const handleInitialQueryConsumed = useCallback(() => {
        setPrefilledQuery(null)
    }, [])

    // NOW we can do conditional returns after all hooks
    // Show loading state while checking auth
    if (loading) {
        return (
            <div className="flex h-screen items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto"></div>
                    <p className="mt-4 text-muted-foreground">Loading...</p>
                </div>
            </div>
        )
    }

    // Don't render main content if not authenticated
    if (!isAuthenticated) {
        return null
    }

    return (
        <div className="flex flex-col h-screen bg-gradient-to-br from-background via-background to-muted/30">
            {/* Guest mode banner */}
            {isGuest && !guestBannerDismissed && (
                <div className="flex items-center justify-center gap-3 px-4 py-2 bg-amber-50 dark:bg-amber-950/40 border-b border-amber-200 dark:border-amber-800 text-xs text-amber-800 dark:text-amber-300 shrink-0">
                    <span>You are in guest mode — sessions are not saved.</span>
                    <a href="/register" className="font-medium underline underline-offset-2 hover:text-amber-900 dark:hover:text-amber-200">
                        Sign up for free
                    </a>
                    <span className="text-amber-600 dark:text-amber-500">to save your history.</span>
                    <button
                        onClick={() => setGuestBannerDismissed(true)}
                        className="ml-2 text-amber-500 hover:text-amber-700 dark:hover:text-amber-200"
                        aria-label="Dismiss"
                    >
                        <X className="w-3.5 h-3.5" />
                    </button>
                </div>
            )}
            {/* Mobile top bar */}
            <div className="flex md:hidden items-center justify-between px-4 py-3 border-b border-border bg-card shrink-0">
                <button
                    onClick={() => setMobileNavOpen(true)}
                    className="p-1.5 rounded-md text-muted-foreground hover:bg-accent"
                    aria-label="Open menu"
                >
                    <Menu className="w-5 h-5" />
                </button>
                <div className="flex items-center gap-1.5">
                    <img src="/logo.png" alt="LinkedOmicsChat" className="h-6 w-auto" />
                    <span className="font-semibold text-sm text-slate-900 dark:text-white">
                        LinkedOmics<span className="text-teal-600 dark:text-teal-400">Chat</span>
                    </span>
                </div>
                {currentView === "chat" && (
                    <button
                        onClick={toggleRightPanel}
                        className="p-1.5 rounded-md text-muted-foreground hover:bg-accent"
                        aria-label="Toggle right panel"
                    >
                        <ChevronLeft className="w-5 h-5" />
                    </button>
                )}
                {currentView !== "chat" && <div className="w-8" />}
            </div>

            <div className="flex flex-1 overflow-hidden">
            <Sidebar
                currentView={currentView}
                onViewChange={handleViewChange}
                currentSessionId={sessionId}
                onSessionChange={handleSessionChange}
                onSearchResultSelect={handleSearchResultSelect}
                mobileOpen={mobileNavOpen}
                onMobileClose={() => setMobileNavOpen(false)}
            />
            <main className="flex-1 overflow-hidden relative">
                {/* All views always mounted — CSS show/hide only, zero React mount cost on switching */}
                <div className="w-full h-full" style={currentView !== "chat" ? { visibility: "hidden", pointerEvents: "none", position: "absolute", top: 0, left: 0 } : {}}>
                    <ChatInterface
                        sessionId={sessionId}
                        onSessionChange={handleSessionChange}
                        onContextUpdate={handleContextUpdate}
                        initialQuery={prefilledQuery}
                        onInitialQueryConsumed={handleInitialQueryConsumed}
                        pendingSearchTarget={pendingSearchTarget}
                        onSearchTargetHandled={(requestKey) => {
                            setPendingSearchTarget((prev) => prev?.requestKey === requestKey ? null : prev)
                        }}
                        focusKey={chatFocusKey}
                    />
                </div>
                {mountedViews.tools && (
                    <div className="w-full h-full" style={currentView !== "tools" ? { visibility: "hidden", pointerEvents: "none", position: "absolute", top: 0, left: 0 } : {}}>
                        <ToolExplorer resetKey={toolsResetKey} />
                    </div>
                )}
                {mountedViews.usecases && (
                    <div className="w-full h-full" style={currentView !== "usecases" ? { visibility: "hidden", pointerEvents: "none", position: "absolute", top: 0, left: 0 } : {}}>
                        <UseCasesPanel
                            onStartChat={(query) => {
                                setPrefilledQuery(query)
                                startTransition(() => setCurrentView("chat"))
                            }}
                        />
                    </div>
                )}
            </main>

            {/* Desktop/tablet right panel toggle button — always mounted, hidden when not in chat view */}
            <button
                onClick={toggleRightPanel}
                className={[
                    "hidden md:flex fixed top-4 z-50 w-6 h-6 rounded-full bg-primary text-primary-foreground shadow-md hover:shadow-lg transition-all duration-300 items-center justify-center",
                    currentView !== "chat" ? "invisible pointer-events-none" : "",
                    !rightPanelOpen ? "right-4" : "",
                    rightPanelOpen ? "right-96 -mr-3" : "",
                ].join(" ")}
                title={rightPanelOpen ? "Collapse right panel" : "Expand right panel"}
                aria-label={rightPanelOpen ? "Collapse right panel" : "Expand right panel"}
                aria-hidden={currentView !== "chat"}
            >
                {rightPanelOpen ? (
                    <ChevronRight className="w-4 h-4" />
                ) : (
                    <ChevronLeft className="w-4 h-4" />
                )}
            </button>

            {/* Desktop/tablet right panel: always mounted, slide in/out */}
            <div
                className={[
                    "hidden md:flex fixed top-0 right-0 z-40 h-full w-96",
                    "border-l border-border bg-card",
                    "transform transition-transform duration-300",
                    rightPanelOpen && currentView === "chat" ? "translate-x-0" : "translate-x-full",
                ].join(" ")}
                aria-hidden={!rightPanelOpen || currentView !== "chat"}
            >
                <RightPanel
                    className="w-full h-full border-l-0"
                    sessionId={sessionId}
                    context={rightPanelContext}
                />
            </div>

            {/* Mobile right panel drawer — always mounted */}
            <div
                className={[
                    "fixed inset-0 z-40 md:hidden",
                    rightPanelOpen && currentView === "chat" ? "pointer-events-auto" : "pointer-events-none",
                ].join(" ")}
                aria-hidden={!rightPanelOpen || currentView !== "chat"}
            >
                {/* Backdrop */}
                <div
                    className={[
                        "absolute inset-0 bg-black/40 transition-opacity duration-200",
                        rightPanelOpen && currentView === "chat" ? "opacity-100" : "opacity-0",
                    ].join(" ")}
                    onClick={() => setRightPanelOpen(false)}
                />
                {/* Slide-over panel */}
                <div
                    className={[
                        "absolute right-0 top-0 h-full w-[90vw] max-w-sm bg-card border-l border-border",
                        "transition-transform duration-200",
                        rightPanelOpen && currentView === "chat" ? "translate-x-0" : "translate-x-full",
                    ].join(" ")}
                >
                    <RightPanel
                        className="w-full h-full border-l-0"
                        sessionId={sessionId}
                        context={rightPanelContext}
                        onClose={() => setRightPanelOpen(false)}
                    />
                </div>
            </div>

            </div>
        </div>
    )
}
