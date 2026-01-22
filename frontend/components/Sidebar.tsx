"use client"

import { useState } from "react"
import Image from "next/image"
import { cn } from "@/lib/utils"
import {
    MessageSquare,
    Database,
    BarChart3,
    Workflow,
    Settings,
    BookOpen,
    ChevronLeft,
    ChevronRight,
    LogOut,
} from "lucide-react"
import { ChatHistory } from "@/components/ChatHistory"
import { useAuth } from "@/components/AuthContext"

type View = "chat" | "datasets" | "visualizations" | "workflows"

interface SidebarProps {
    currentView: View
    onViewChange: (view: View) => void
    currentSessionId: string | null
    onSessionChange: (sessionId: string | null) => void
    onSettingsOpen: () => void
}

const navItems: Array<{ id: View; label: string; icon: any }> = [
    { id: "chat", label: "Chat", icon: MessageSquare },
    { id: "datasets", label: "Datasets", icon: Database },
    { id: "visualizations", label: "Visualizations", icon: BarChart3 },
    { id: "workflows", label: "Workflows", icon: Workflow },
]

export function Sidebar({ currentView, onViewChange, currentSessionId, onSessionChange, onSettingsOpen }: SidebarProps) {
    const [isCollapsed, setIsCollapsed] = useState(false)
    const { user, logout } = useAuth()

    return (
        <div className={cn(
            "bg-card border-r border-border flex flex-col transition-all duration-300 relative",
            isCollapsed ? "w-16" : "w-64"
        )}>
            {/* Toggle Button */}
            <button
                onClick={() => setIsCollapsed(!isCollapsed)}
                className="absolute top-4 -right-3 z-10 w-6 h-6 rounded-full bg-primary text-primary-foreground shadow-md hover:shadow-lg transition-all flex items-center justify-center"
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
                        <div className="flex items-center gap-3 relative">
                            {/* Light mode logo */}
                            <Image 
                                src="/cpgagent.png"
                                alt="cpgAgent Logo" 
                                width={200}
                                height={60}
                                className="w-full h-auto dark:hidden"
                                priority
                            />
                            {/* Dark mode logo */}
                            <Image 
                                src="/cpgagent-dark.png"
                                alt="cpgAgent Logo" 
                                width={200}
                                height={60}
                                className="w-full h-auto hidden dark:block"
                                priority
                            />
                        </div>
                        <p className="text-sm text-muted-foreground mt-3">
                            AI-Powered Omics Platform
                        </p>
                    </>
                ) : (
                    <div className="flex justify-center">
                        <MessageSquare className="w-8 h-8 text-primary" />
                    </div>
                )}
            </div>

            {/* Navigation */}
            <nav className={cn("p-4 space-y-2 border-b border-border", isCollapsed && "p-2")}>
                {navItems.map((item) => {
                    const Icon = item.icon
                    const isActive = currentView === item.id

                    return (
                        <button
                            key={item.id}
                            onClick={() => onViewChange(item.id)}
                            className={cn(
                                "w-full flex items-center rounded-lg transition-all font-medium",
                                isCollapsed ? "justify-center p-3" : "gap-3 px-4 py-3 text-left",
                                isActive
                                    ? "bg-primary text-primary-foreground shadow-md"
                                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                            )}
                            title={isCollapsed ? item.label : undefined}
                        >
                            <Icon className="h-5 w-5" />
                            {!isCollapsed && <span>{item.label}</span>}
                        </button>
                    )
                })}
            </nav>

            {/* Chat History (only show when in chat view and not collapsed) */}
            {currentView === "chat" && !isCollapsed && (
                <div className="flex-1 overflow-hidden flex flex-col">
                    <ChatHistory 
                        currentSessionId={currentSessionId}
                        onSessionSelect={(sessionId) => {
                            onSessionChange(sessionId)
                            onViewChange("chat")
                        }}
                    />
                </div>
            )}

            {/* Footer */}
            <div className={cn("p-4 border-t border-border space-y-2", isCollapsed && "p-2")}>
                {!isCollapsed && user && (
                    <div className="px-4 py-2 mb-2 text-sm">
                        <p className="font-medium text-foreground">{user.username}</p>
                        <p className="text-xs text-muted-foreground truncate">{user.email}</p>
                    </div>
                )}
                <a
                    href="/docs"
                    className={cn(
                        "w-full flex items-center rounded-lg transition-all font-medium text-muted-foreground",
                        isCollapsed ? "justify-center p-3" : "gap-3 px-4 py-3 text-left",
                        "hover:bg-accent hover:text-accent-foreground"
                    )}
                    title={isCollapsed ? "Documentation" : undefined}
                >
                    <BookOpen className="h-5 w-5" />
                    {!isCollapsed && <span>Documentation</span>}
                </a>
                <button
                    onClick={onSettingsOpen}
                    className={cn(
                        "w-full flex items-center rounded-lg transition-all font-medium",
                        isCollapsed ? "justify-center p-3" : "gap-3 px-4 py-3 text-left",
                        "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    )}
                    title={isCollapsed ? "Settings" : undefined}
                >
                    <Settings className="h-5 w-5" />
                    {!isCollapsed && <span>Settings</span>}
                </button>
                <button
                    onClick={logout}
                    className={cn(
                        "w-full flex items-center rounded-lg transition-all font-medium",
                        isCollapsed ? "justify-center p-3" : "gap-3 px-4 py-3 text-left",
                        "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                    )}
                    title={isCollapsed ? "Logout" : undefined}
                >
                    <LogOut className="h-5 w-5" />
                    {!isCollapsed && <span>Logout</span>}
                </button>
            </div>
        </div>
    )
}
