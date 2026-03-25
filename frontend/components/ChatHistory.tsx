"use client"

import { useState, useEffect, useRef } from "react"
import { Trash2, MessageSquare, Plus, Pencil, Check, X, Search } from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { chatAPI } from "@/lib/api"
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
} from "@/components/ui/alert-dialog"

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
    onSearchResultSelect?: (target: { sessionId: string; messageId: number }) => void
}

// Export loadSessions function so it can be called from parent
export interface ChatHistoryRef {
    refresh: () => void
}

interface SearchResult {
    message_id: number
    session_id: string
    session_title: string
    query: string
    excerpt: string
    timestamp: number
}

export function ChatHistory({ currentSessionId, onSessionSelect, onSearchResultSelect }: ChatHistoryProps) {
    const [sessions, setSessions] = useState<ChatSession[]>([])
    const [isLoading, setIsLoading] = useState(true) // Initial load only
    const [editingId, setEditingId] = useState<string | null>(null)
    const [editingTitle, setEditingTitle] = useState("")
    const [searchQuery, setSearchQuery] = useState("")
    const [searchResults, setSearchResults] = useState<SearchResult[] | null>(null)
    const [isSearching, setIsSearching] = useState(false)
    const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    useEffect(() => {
        loadSessions(true) // Initial load with loading state

        // Keep sidebar data fresh without constantly competing with chat/history requests.
        const interval = setInterval(() => loadSessions(false), 30000)
        return () => clearInterval(interval)
    }, [])

    // Refresh only when the selected session is new or still using the placeholder title.
    // Switching between existing named chats should not reload the whole session list.
    useEffect(() => {
        if (currentSessionId) {
            const selected = sessions.find((session) => session.session_id === currentSessionId)
            const needsRefresh = !selected || !selected.title || selected.title === "New Chat"
            if (!needsRefresh) {
                return
            }
            loadSessions(false)
            const t1 = setTimeout(() => loadSessions(false), 3000)
            return () => { clearTimeout(t1) }
        }
    }, [currentSessionId])

    // Debounced cross-session search
    useEffect(() => {
        if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
        if (!searchQuery.trim()) {
            setSearchResults(null)
            return
        }
        searchDebounceRef.current = setTimeout(async () => {
            setIsSearching(true)
            try {
                const data = await chatAPI.searchMessages(searchQuery.trim())
                setSearchResults(data.results)
            } catch {
                setSearchResults([])
            } finally {
                setIsSearching(false)
            }
        }, 300)
        return () => { if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current) }
    }, [searchQuery])

    const loadSessions = async (showLoading: boolean = false) => {
        try {
            if (showLoading) {
                setIsLoading(true)
            }
            const data = await chatAPI.listSessions()
            setSessions(data.sessions || [])
        } catch (error) {
            console.error("Failed to load sessions:", error)
            // If unauthorized, clear sessions (user logged out)
            if (error instanceof Error && error.message.includes("401")) {
                setSessions([])
            }
        } finally {
            if (showLoading) {
                setIsLoading(false)
            }
        }
    }

    const deleteSession = async (sessionId: string, e?: React.MouseEvent) => {
        if (e) e.stopPropagation()

        try {
            await chatAPI.clearSession(sessionId)
            setSessions(sessions.filter(s => s.session_id !== sessionId))
            if (currentSessionId === sessionId) {
                onSessionSelect(null)
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
            await chatAPI.updateSessionTitle(sessionId, editingTitle.trim())
            // Update local state
            setSessions(sessions.map(s =>
                s.session_id === sessionId
                    ? { ...s, title: editingTitle.trim() }
                    : s
            ))
            cancelEditing()
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
                    className="w-full gap-2 bg-primary text-primary-foreground shadow-sm hover:shadow-md transition-all duration-200"
                >
                    <Plus className="h-4 w-4" />
                    New Chat
                </Button>
            </div>

            {/* Cross-session search */}
            <div className="px-3 py-2 border-b border-border">
                <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-muted/50 border border-border focus-within:border-primary/50 transition-colors">
                    <Search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                    <input
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        placeholder="Search all chats…"
                        className="flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground"
                    />
                    {searchQuery && (
                        <button onClick={() => setSearchQuery("")} className="text-muted-foreground hover:text-foreground">
                            <X className="w-3 h-3" />
                        </button>
                    )}
                </div>
            </div>

            {/* Chat List / Search Results */}
            <div className="flex-1 overflow-y-auto p-2">
                {searchQuery.trim() ? (
                    // Search results view
                    isSearching ? (
                        <div className="text-center text-muted-foreground py-8 text-sm">Searching…</div>
                    ) : searchResults && searchResults.length === 0 ? (
                        <div className="text-center text-muted-foreground py-8 text-sm">No results for &ldquo;{searchQuery}&rdquo;</div>
                    ) : searchResults ? (
                        <div className="space-y-1">
                            {searchResults.map(result => (
                                <div
                                    key={result.message_id}
                                    onClick={() => {
                                        if (onSearchResultSelect) {
                                            onSearchResultSelect({
                                                sessionId: result.session_id,
                                                messageId: result.message_id,
                                            })
                                        } else {
                                            onSessionSelect(result.session_id)
                                        }
                                    }}
                                    className="cursor-pointer p-3 rounded-lg hover:bg-accent transition-all border border-transparent hover:border-border"
                                >
                                    <p className="text-xs font-semibold text-primary truncate mb-1">{result.session_title}</p>
                                    <p className="text-xs font-medium truncate">{result.query}</p>
                                    <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{result.excerpt}</p>
                                </div>
                            ))}
                        </div>
                    ) : null
                ) : isLoading ? (
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
                                            <AlertDialog>
                                                <AlertDialogTrigger asChild>
                                                    <button
                                                        onClick={(e) => e.stopPropagation()}
                                                        className="p-1 hover:bg-destructive/10 rounded transition-all"
                                                        title="Delete chat"
                                                    >
                                                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                                                    </button>
                                                </AlertDialogTrigger>
                                                <AlertDialogContent onClick={(e) => e.stopPropagation()}>
                                                    <AlertDialogHeader>
                                                        <AlertDialogTitle>Delete Chat Session?</AlertDialogTitle>
                                                        <AlertDialogDescription>
                                                            Are you sure you want to delete "{session.title}"? This action cannot be undone.
                                                        </AlertDialogDescription>
                                                    </AlertDialogHeader>
                                                    <AlertDialogFooter>
                                                        <AlertDialogCancel onClick={(e) => e.stopPropagation()}>Cancel</AlertDialogCancel>
                                                        <AlertDialogAction
                                                            onClick={(e) => deleteSession(session.session_id, e)}
                                                            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                                                        >
                                                            Delete
                                                        </AlertDialogAction>
                                                    </AlertDialogFooter>
                                                </AlertDialogContent>
                                            </AlertDialog>
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
