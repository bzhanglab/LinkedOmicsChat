"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import {
    MessageSquare,
    ChevronLeft,
    ChevronRight,
    LogOut,
    Wrench,
    Lightbulb,
    Sun,
    Moon,
    Monitor,
} from "lucide-react"
import { ChatHistory } from "@/components/ChatHistory"
import { useAuth } from "@/components/AuthContext"
import { useTheme } from "@/components/ThemeProvider"

type View = "chat" | "tools" | "usecases"

interface SidebarProps {
    currentView: View
    onViewChange: (view: View) => void
    currentSessionId: string | null
    onSessionChange: (sessionId: string | null) => void
    onSearchResultSelect?: (target: { sessionId: string; messageId: number }) => void
    mobileOpen?: boolean
    onMobileClose?: () => void
}

const navItems: Array<{ id: View; label: string; icon: any; href: string; separator?: boolean; placeholder?: boolean; hidden?: boolean }> = [
    { id: "chat", label: "Chat", icon: MessageSquare, href: "/" },
    { id: "tools", label: "Tools", icon: Wrench, href: "/?view=tools" },
    { id: "usecases", label: "Use Cases", icon: Lightbulb, href: "/?view=usecases" },
]

export function Sidebar({ currentView, onViewChange, currentSessionId, onSessionChange, onSearchResultSelect, mobileOpen = false, onMobileClose }: SidebarProps) {
    const [isCollapsed, setIsCollapsed] = useState(false)
    const { user, logout, isGuest } = useAuth()
    const { theme, setTheme } = useTheme()

    const handleNavClick = (view: View, placeholder?: boolean) => {
        if (!placeholder) {
            onViewChange(view)
            onMobileClose?.()
        }
    }

    return (
        <>
        {/* Mobile backdrop */}
        <div
            className={cn(
                "fixed inset-0 z-40 bg-black/40 md:hidden transition-opacity duration-200",
                mobileOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"
            )}
            onClick={onMobileClose}
        />

        <div className={cn(
            "bg-card border-r border-border flex flex-col transition-all duration-300",
            // Mobile: fixed drawer, slides in from left
            "fixed inset-y-0 left-0 z-50 w-72 transition-transform",
            mobileOpen ? "translate-x-0" : "-translate-x-full",
            // Desktop: inline in layout, overrides mobile fixed positioning
            "md:relative md:inset-auto md:z-10 md:translate-x-0 md:transition-all md:duration-300",
            isCollapsed ? "md:w-16" : "md:w-64"
        )}>
            {/* Toggle Button — desktop only */}
            <button
                onClick={() => setIsCollapsed(!isCollapsed)}
                className="hidden md:flex absolute top-4 -right-3 z-20 w-6 h-6 rounded-full bg-primary text-primary-foreground shadow-md hover:shadow-lg transition-all items-center justify-center"
                title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
                {isCollapsed ? (
                    <ChevronRight className="w-4 h-4" />
                ) : (
                    <ChevronLeft className="w-4 h-4" />
                )}
            </button>

            {/* Header */}
            <div className={cn("p-6 border-b border-border", isCollapsed && "p-2")}>
                {!isCollapsed ? (
                    <>
                        <div className="flex items-center gap-2.5">
                            <img src="/logo.png" alt="LinkedOmicsChat" className="h-7 w-auto" />
                            <span className="text-xl font-bold tracking-tight text-slate-900 dark:text-white">
                                LinkedOmics<span className="text-teal-600 dark:text-teal-400">Chat</span>
                            </span>
                        </div>
                        <p className="text-sm text-muted-foreground mt-1">
                            Multi-Omics AI Platform
                        </p>
                    </>
                ) : (
                    <div className="flex justify-center">
                        <img src="/logo.png" alt="LinkedOmicsChat" className="h-8 w-auto" />
                    </div>
                )}
            </div>

            {/* Navigation */}
            <nav className={cn("p-4 space-y-2 border-b border-border", isCollapsed && "p-2")}>
                {navItems.filter((item) => !item.hidden).map((item, index) => {
                    const Icon = item.icon
                    const isActive = currentView === item.id

                    return (
                        <div key={item.id}>
                            {/* Separator line before placeholder items */}
                            {item.separator && !isCollapsed && (
                                <div className="my-3 border-t border-border" />
                            )}
                            <a
                                href={item.placeholder ? undefined : item.href}
                                onClick={(e) => {
                                    if (item.placeholder) return
                                    e.preventDefault()
                                    handleNavClick(item.id, item.placeholder)
                                }}
                                className={cn(
                                    "w-full flex items-center rounded-lg transition-all font-medium relative",
                                    isCollapsed ? "justify-center p-3" : "gap-3 px-4 py-3 text-left",
                                    item.placeholder && "opacity-50 cursor-not-allowed",
                                    !item.placeholder && isActive
                                        ? "bg-primary text-primary-foreground shadow-md"
                                        : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                                    item.placeholder && "hover:bg-transparent"
                                )}
                                title={isCollapsed ? item.label : item.placeholder ? "Coming soon" : undefined}
                            >
                                <Icon className="h-5 w-5" />
                                {!isCollapsed && (
                                    <div className="flex items-center justify-between flex-1">
                                        <span>{item.label}</span>
                                        {item.placeholder && (
                                            <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                                                Soon
                                            </span>
                                        )}
                                    </div>
                                )}
                            </a>
                        </div>
                    )
                })}
            </nav>

            {/* Content area - always takes remaining space */}
            <div className="flex-1 overflow-hidden flex flex-col min-h-0">
                {/* Chat History — always visible when sidebar is expanded */}
                {!isCollapsed && !isGuest && (
                    <ChatHistory
                        currentSessionId={currentSessionId}
                        onSessionSelect={(sessionId) => {
                            onSessionChange(sessionId)
                            onViewChange("chat")
                        }}
                        onSearchResultSelect={onSearchResultSelect ? (target) => {
                            onSearchResultSelect(target)
                            onMobileClose?.()
                        } : undefined}
                    />
                )}
                {/* Guest: prompt to sign up */}
                {!isCollapsed && isGuest && (
                    <div className="p-4 text-xs text-muted-foreground space-y-2">
                        <p>Chat history is not saved in guest mode.</p>
                        <a href="/register" className="text-primary hover:underline block">
                            Sign up →
                        </a>
                    </div>
                )}
            </div>

            {/* Footer */}
            <div className={cn("p-4 border-t border-border space-y-2", isCollapsed && "p-2")}>
                {!isCollapsed && user && (
                    <div className="px-4 py-2 mb-2 text-sm">
                        <p className="font-medium text-foreground">{user.username}</p>
                        <p className="text-xs text-muted-foreground truncate">{user.email}</p>
                    </div>
                )}
                {!isCollapsed && isGuest && (
                    <div className="px-4 py-2 mb-2 text-sm">
                        <p className="font-medium text-foreground">Guest</p>
                        <p className="text-xs text-muted-foreground">Session not saved</p>
                    </div>
                )}
                {/* Theme toggle */}
                {!isCollapsed ? (
                    <div className="px-4 py-2">
                        <p className="text-xs text-muted-foreground mb-2">Theme</p>
                        <div className="grid grid-cols-3 gap-1">
                            {([
                                { value: "light", icon: Sun, label: "Light" },
                                { value: "dark", icon: Moon, label: "Dark" },
                                { value: "system", icon: Monitor, label: "System" },
                            ] as const).map(({ value, icon: Icon, label }) => (
                                <button
                                    key={value}
                                    onClick={() => setTheme(value)}
                                    className={cn(
                                        "flex flex-col items-center gap-1 py-1.5 rounded-md text-xs font-medium transition-colors",
                                        theme === value
                                            ? "bg-primary/10 text-primary border border-primary/30"
                                            : "text-muted-foreground hover:bg-accent hover:text-accent-foreground border border-transparent"
                                    )}
                                    title={label}
                                >
                                    <Icon className="h-3.5 w-3.5" />
                                    {label}
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    <button
                        onClick={() => setTheme(theme === "light" ? "dark" : theme === "dark" ? "system" : "light")}
                        className="w-full flex justify-center p-3 rounded-lg text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
                        title={`Theme: ${theme}`}
                    >
                        {theme === "dark" ? <Moon className="h-5 w-5" /> : theme === "light" ? <Sun className="h-5 w-5" /> : <Monitor className="h-5 w-5" />}
                    </button>
                )}
                <button
                    onClick={isGuest ? () => { window.location.href = "/login" } : logout}
                    className={cn(
                        "w-full flex items-center rounded-lg transition-all font-medium",
                        isCollapsed ? "justify-center p-3" : "gap-3 px-4 py-3 text-left",
                        "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    )}
                    title={isCollapsed ? (isGuest ? "Sign in" : "Logout") : undefined}
                >
                    <LogOut className="h-5 w-5" />
                    {!isCollapsed && <span>{isGuest ? "Sign in" : "Logout"}</span>}
                </button>
                {!isCollapsed && (
                    <p className="px-4 pt-1 text-xs text-muted-foreground">
                        &copy; 2026 Zhang Lab &middot;{" "}
                        <a href="/about" target="_blank" rel="noopener noreferrer" className="hover:underline">About</a>
                        {" "}&middot;{" "}
                        <a href="https://github.com/bzhanglab/LinkedOmicsChat/issues" target="_blank" rel="noopener noreferrer" className="hover:underline">Feedback</a>
                        {process.env.NEXT_PUBLIC_APP_VERSION && (
                            <span className="ml-1 text-muted-foreground/60">v{process.env.NEXT_PUBLIC_APP_VERSION}</span>
                        )}
                    </p>
                )}
            </div>
        </div>
        </>
    )
}
