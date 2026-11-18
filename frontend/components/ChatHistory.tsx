"use client"

import React, { useState, useEffect, useRef } from "react"
import { Trash2, MessageSquare, Plus, Pencil, Check, X, Search, Pin, PinOff } from "lucide-react"
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
    pinned?: boolean
    shared?: boolean
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

/** Wrap each occurrence of `term` in <mark> for inline highlighting. */
function highlightText(text: string, term: string): React.ReactNode {
    if (!term.trim()) return text
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    const parts = text.split(new RegExp(`(${escaped})`, "gi"))
    return parts.map((part, i) =>
        part.toLowerCase() === term.toLowerCase()
            ? <mark key={i} className="bg-amber-200 dark:bg-amber-700/60 text-inherit rounded-sm px-0.5">{part}</mark>
            : part
    )
}

export function ChatHistory({ currentSessionId, onSessionSelect, onSearchResultSelect }: ChatHistoryProps) {
    const [sessions, setSessions] = useState<ChatSession[]>([])
    const [isLoading, setIsLoading] = useState(true) // Initial load only
    const [editingId, setEditingId] = useState<string | null>(null)
    const [editingTitle, setEditingTitle] = useState("")
    // Enter, Save, and clicking away can each end the same edit; this lets only the first one count
    const editingIdRef = useRef<string | null>(null)
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

    // Clear search when the user switches to a different session
    useEffect(() => {
        setSearchQuery("")
    }, [currentSessionId])

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

    // Pinned chats are listed first and cannot be deleted (the server refuses too) until unpinned
    const togglePin = async (session: ChatSession, e: React.MouseEvent) => {
        e.stopPropagation()
        const pinned = !session.pinned
        try {
            await chatAPI.setSessionPinned(session.session_id, pinned)
            setSessions(prev => prev.map(s => s.session_id === session.session_id ? { ...s, pinned } : s))
        } catch (error) {
            console.error("Failed to pin session:", error)
        }
    }

    const pinnedCount = sessions.filter(s => s.pinned).length
    const orderedSessions = [...sessions.filter(s => s.pinned), ...sessions.filter(s => !s.pinned)]

    const startEditing = (sessionId: string, currentTitle: string, e: React.MouseEvent) => {
        e.stopPropagation()
        editingIdRef.current = sessionId
        setEditingId(sessionId)
        setEditingTitle(currentTitle)
    }

    const cancelEditing = () => {
        editingIdRef.current = null
        setEditingId(null)
        setEditingTitle("")
    }

    const saveTitle = async (sessionId: string) => {
        if (editingIdRef.current !== sessionId) return
        editingIdRef.current = null
        const title = editingTitle.trim()
        if (!title || title === sessions.find(s => s.session_id === sessionId)?.title) {
            cancelEditing()
            return
        }

        try {
            await chatAPI.updateSessionTitle(sessionId, title)
            // Update local state
            setSessions(sessions.map(s =>
                s.session_id === sessionId
                    ? { ...s, title }
                    : s
            ))
            cancelEditing()
        } catch (error) {
            console.error("Failed to update title:", error)
            editingIdRef.current = sessionId  // keep editing so the user can try again
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
                                    <p className="text-xs font-medium truncate">{highlightText(result.query, searchQuery)}</p>
                                    <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{highlightText(result.excerpt, searchQuery)}</p>
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
                        {orderedSessions.map((session, index) => (
                            <React.Fragment key={session.session_id}>
                            {index === 0 && session.pinned && (
                                <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Pinned</p>
                            )}
                            {index === pinnedCount && pinnedCount > 0 && (
                                <p className="px-3 pt-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Recent</p>
                            )}
                            <div
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
                                    // Editing Mode - Full width layout. Clicking away saves, as Enter does.
                                    <div
                                        className="space-y-2"
                                        onClick={(e) => e.stopPropagation()}
                                        onBlur={(e) => {
                                            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) saveTitle(session.session_id)
                                        }}
                                    >
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
                                            {/* preventDefault keeps focus in the box, so pressing Cancel (Safari does not focus buttons) is not taken as clicking away */}
                                            <button
                                                onMouseDown={(e) => e.preventDefault()}
                                                onClick={cancelEditing}
                                                className="px-3 py-1 text-xs rounded hover:bg-muted transition-colors flex items-center gap-1"
                                                title="Cancel"
                                            >
                                                <X className="h-3 w-3" />
                                                Cancel
                                            </button>
                                            <button
                                                onMouseDown={(e) => e.preventDefault()}
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
                                        {session.pinned
                                            ? <Pin className="h-4 w-4 mt-0.5 text-primary flex-shrink-0" />
                                            : <MessageSquare className="h-4 w-4 mt-0.5 text-muted-foreground flex-shrink-0" />}
                                        <div className="flex-1 min-w-0">
                                            <p className="text-sm font-medium line-clamp-2 break-words" title={session.title}>
                                                {session.title}
                                            </p>
                                            <p className="text-xs text-muted-foreground mt-0.5 truncate">
                                                {session.message_count} messages · {formatDate(session.last_updated)}
                                            </p>
                                        </div>
                                        {/* On desktop the buttons appear over the end of the row on hover, so the title keeps the full width; touch screens have no hover, so they stay visible there */}
                                        <div className="flex gap-1 flex-shrink-0 md:hidden md:group-hover:flex md:group-focus-within:flex md:absolute md:right-2 md:top-2 md:rounded-md md:bg-accent md:px-1 md:py-0.5">
                                            <button
                                                onClick={(e) => togglePin(session, e)}
                                                className="p-1 hover:bg-primary/10 rounded transition-all"
                                                title={session.pinned ? "Unpin chat" : "Pin chat (pinned chats cannot be deleted)"}
                                            >
                                                {session.pinned
                                                    ? <PinOff className="h-3.5 w-3.5 text-muted-foreground" />
                                                    : <Pin className="h-3.5 w-3.5 text-muted-foreground" />}
                                            </button>
                                            <button
                                                onClick={(e) => startEditing(session.session_id, session.title, e)}
                                                className="p-1 hover:bg-primary/10 rounded transition-all"
                                                title="Rename chat"
                                            >
                                                <Pencil className="h-3.5 w-3.5 text-muted-foreground" />
                                            </button>
                                            {!session.pinned && (
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
                                                            {session.shared && (
                                                                <span className="block mt-2 font-medium text-destructive">
                                                                    This chat has a public share link. Deleting it will break that link for anyone who has it.
                                                                </span>
                                                            )}
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
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>
                            </React.Fragment>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
