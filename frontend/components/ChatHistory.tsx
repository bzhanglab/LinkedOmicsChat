"use client"

import { useState, useEffect } from "react"
import { Trash2, MessageSquare, Plus, Pencil, Check, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { API_URL } from "@/lib/api"

interface ChatSession {
    session_id: string
    title: string
    created_at: string | number
    last_updated: string | number
    message_count: number
}

interface ChatHistoryProps {
    currentSessionId: string | null
    onSessionSelect: (sessionId: string | null) => void
}

// Export loadSessions function so it can be called from parent
export interface ChatHistoryRef {
    refresh: () => void
}

export function ChatHistory({ currentSessionId, onSessionSelect }: ChatHistoryProps) {
    const [sessions, setSessions] = useState<ChatSession[]>([])
    const [isLoading, setIsLoading] = useState(true) // Initial load only
    const [editingId, setEditingId] = useState<string | null>(null)
    const [editingTitle, setEditingTitle] = useState("")

    useEffect(() => {
        loadSessions(true) // Initial load with loading state
        
        // Refresh sessions more frequently to catch title updates (every 5 seconds)
        const interval = setInterval(() => loadSessions(false), 5000)
        return () => clearInterval(interval)
    }, [])

    // Reload sessions when current session changes
    useEffect(() => {
        if (currentSessionId) {
            loadSessions(false) // Background refresh, no loading state
            // Also refresh after a short delay to catch title updates
            const timeout = setTimeout(() => loadSessions(false), 2000)
            return () => clearTimeout(timeout)
        }
    }, [currentSessionId])

    const loadSessions = async (showLoading: boolean = false) => {
        try {
            if (showLoading) {
                setIsLoading(true)
            }
            const response = await fetch(`${API_URL}/api/v1/chat/sessions`)
            if (response.ok) {
                const data = await response.json()
                setSessions(data.sessions || [])
            }
        } catch (error) {
            console.error("Failed to load sessions:", error)
        } finally {
            if (showLoading) {
                setIsLoading(false)
            }
        }
    }

    const deleteSession = async (sessionId: string, e: React.MouseEvent) => {
        e.stopPropagation()
        
        if (!confirm("Delete this chat? This cannot be undone.")) {
            return
        }

        try {
            const response = await fetch(
                `${API_URL}/api/v1/chat/sessions/${sessionId}`,
                { method: "DELETE" }
            )
            
            if (response.ok) {
                setSessions(sessions.filter(s => s.session_id !== sessionId))
                if (currentSessionId === sessionId) {
                    onSessionSelect(null)
                }
            }
        } catch (error) {
            console.error("Failed to delete session:", error)
        }
    }

    const startEditing = (sessionId: string, currentTitle: string, e: React.MouseEvent) => {
        e.stopPropagation()
        setEditingId(sessionId)
        setEditingTitle(currentTitle)
    }

    const cancelEditing = () => {
        setEditingId(null)
        setEditingTitle("")
    }

    const saveTitle = async (sessionId: string) => {
        if (!editingTitle.trim()) {
            cancelEditing()
            return
        }

        try {
            const response = await fetch(
                `${API_URL}/api/v1/chat/sessions/${sessionId}/title`,
                {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ title: editingTitle.trim() })
                }
            )
            
            if (response.ok) {
                // Update local state
                setSessions(sessions.map(s => 
                    s.session_id === sessionId 
                        ? { ...s, title: editingTitle.trim() }
                        : s
                ))
                cancelEditing()
            }
        } catch (error) {
            console.error("Failed to update title:", error)
        }
    }

    const handleKeyDown = (e: React.KeyboardEvent, sessionId: string) => {
        if (e.key === "Enter") {
            saveTitle(sessionId)
        } else if (e.key === "Escape") {
            cancelEditing()
        }
    }

    const startNewChat = () => {
        onSessionSelect(null)
    }

    const formatDate = (timestamp: string | number) => {
        // Convert timestamp to Date (handle both Unix timestamps and ISO strings)
        const date = typeof timestamp === 'number' 
            ? new Date(timestamp)  // Already in milliseconds from API
            : new Date(timestamp)
        
        const now = new Date()
        const diffMs = now.getTime() - date.getTime()
        const diffMins = Math.floor(diffMs / 60000)
        const diffHours = Math.floor(diffMs / 3600000)
        const diffDays = Math.floor(diffMs / 86400000)

        if (diffMins < 1) return "Just now"
        if (diffMins < 60) return `${diffMins}m ago`
        if (diffHours < 24) return `${diffHours}h ago`
        if (diffDays < 7) return `${diffDays}d ago`
        return date.toLocaleDateString()
    }

    return (
        <div className="flex flex-col h-full">
            {/* New Chat Button */}
            <div className="p-3 border-b border-border">
                <Button
                    onClick={startNewChat}
                    className="w-full gap-2"
                    variant={currentSessionId ? "outline" : "default"}
                >
                    <Plus className="h-4 w-4" />
                    New Chat
                </Button>
            </div>

            {/* Chat List */}
            <div className="flex-1 overflow-y-auto p-2">
                {isLoading ? (
                    <div className="text-center text-muted-foreground py-8">
                        Loading chats...
                    </div>
                ) : sessions.length === 0 ? (
                    <div className="text-center text-muted-foreground py-8 text-sm">
                        No previous chats
                    </div>
                ) : (
                    <div className="space-y-1">
                        {sessions.map((session) => (
                            <div
                                key={session.session_id}
                                onClick={() => editingId !== session.session_id && onSessionSelect(session.session_id)}
                                className={cn(
                                    "group relative p-3 rounded-lg transition-all",
                                    editingId === session.session_id 
                                        ? "bg-accent border border-primary" 
                                        : "cursor-pointer hover:bg-accent",
                                    currentSessionId === session.session_id && editingId !== session.session_id
                                        ? "bg-accent border border-primary"
                                        : editingId !== session.session_id && "border border-transparent"
                                )}
                            >
                                {editingId === session.session_id ? (
                                    // Editing Mode - Full width layout
                                    <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                                        <div className="flex items-center gap-2">
                                            <MessageSquare className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                                            <input
                                                type="text"
                                                value={editingTitle}
                                                onChange={(e) => setEditingTitle(e.target.value)}
                                                onKeyDown={(e) => handleKeyDown(e, session.session_id)}
                                                className="flex-1 text-sm font-medium px-2 py-1.5 bg-background border border-primary rounded focus:outline-none focus:ring-2 focus:ring-primary/20"
                                                autoFocus
                                                placeholder="Enter chat title..."
                                            />
                                        </div>
                                        <div className="flex items-center justify-end gap-2 pl-6">
                                            <button
                                                onClick={cancelEditing}
                                                className="px-3 py-1 text-xs rounded hover:bg-muted transition-colors flex items-center gap-1"
                                                title="Cancel"
                                            >
                                                <X className="h-3 w-3" />
                                                Cancel
                                            </button>
                                            <button
                                                onClick={() => saveTitle(session.session_id)}
                                                className="px-3 py-1 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors flex items-center gap-1"
                                                title="Save"
                                            >
                                                <Check className="h-3 w-3" />
                                                Save
                                            </button>
                                        </div>
                                    </div>
                                ) : (
                                    // Normal Mode
                                    <div className="flex items-start gap-2">
                                        <MessageSquare className="h-4 w-4 mt-0.5 text-muted-foreground flex-shrink-0" />
                                        <div className="flex-1 min-w-0">
                                            <p className="text-sm font-medium truncate">
                                                {session.title}
                                            </p>
                                            <p className="text-xs text-muted-foreground mt-0.5">
                                                {session.message_count} messages · {formatDate(session.last_updated)}
                                            </p>
                                        </div>
                                        <div className="opacity-0 group-hover:opacity-100 flex gap-1 flex-shrink-0">
                                            <button
                                                onClick={(e) => startEditing(session.session_id, session.title, e)}
                                                className="p-1 hover:bg-primary/10 rounded transition-all"
                                                title="Rename chat"
                                            >
                                                <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                                            </button>
                                            <button
                                                onClick={(e) => deleteSession(session.session_id, e)}
                                                className="p-1 hover:bg-destructive/10 rounded transition-all"
                                                title="Delete chat"
                                            >
                                                <Trash2 className="h-3.5 w-3.5 text-destructive" />
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
