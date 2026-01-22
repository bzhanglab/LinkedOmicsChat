"use client"

import { useState, useEffect } from "react"
import { Sidebar } from "@/components/Sidebar"
import { ChatInterface } from "@/components/ChatInterface"
import { DatasetsPanel } from "@/components/DatasetsPanel"
import { VisualizationsPanel } from "@/components/VisualizationsPanel"
import { WorkflowsPanel } from "@/components/WorkflowsPanel"
import { SettingsPanel } from "@/components/SettingsPanel"
import { API_URL } from "@/lib/api"

type View = "chat" | "datasets" | "visualizations" | "workflows"

export default function Home() {
    const [currentView, setCurrentView] = useState<View>("chat")
    const [settingsOpen, setSettingsOpen] = useState(false)
    // Initialize sessionId from localStorage synchronously to prevent flash
    const [sessionId, setSessionId] = useState<string | null>(() => {
        if (typeof window !== "undefined") {
            return localStorage.getItem("cpgagent-current-session")
        }
        return null
    })

    // Verify session exists after mount (only on initial load)
    useEffect(() => {
        const savedSessionId = localStorage.getItem("cpgagent-current-session")
        if (savedSessionId && savedSessionId === sessionId) {
            // Only verify if this is the session we loaded from localStorage
            fetch(`${API_URL}/api/v1/chat/sessions/${savedSessionId}`)
                .then(response => {
                    if (!response.ok) {
                        // Session doesn't exist, clear it
                        setSessionId(null)
                        localStorage.removeItem("cpgagent-current-session")
                    }
                })
                .catch(() => {
                    // On error, clear invalid session
                    setSessionId(null)
                    localStorage.removeItem("geneagent-current-session")
                })
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []) // Only run on mount

    // Save sessionId to localStorage whenever it changes
    useEffect(() => {
        if (sessionId) {
            localStorage.setItem("cpgagent-current-session", sessionId)
        } else {
            localStorage.removeItem("geneagent-current-session")
        }
    }, [sessionId])

    const renderView = () => {
        switch (currentView) {
            case "chat":
                return <ChatInterface sessionId={sessionId} onSessionChange={setSessionId} />
            case "datasets":
                return <DatasetsPanel />
            case "visualizations":
                return <VisualizationsPanel />
            case "workflows":
                return <WorkflowsPanel />
            default:
                return <ChatInterface sessionId={sessionId} onSessionChange={setSessionId} />
        }
    }

    return (
        <div className="flex h-screen bg-background">
            <Sidebar 
                currentView={currentView} 
                onViewChange={setCurrentView}
                currentSessionId={sessionId}
                onSessionChange={setSessionId}
                onSettingsOpen={() => setSettingsOpen(true)}
            />
            <main className="flex-1 overflow-hidden">
                {renderView()}
            </main>
            {settingsOpen && (
                <SettingsPanel open={settingsOpen} onOpenChange={setSettingsOpen} />
            )}
        </div>
    )
}
