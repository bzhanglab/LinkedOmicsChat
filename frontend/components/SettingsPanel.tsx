"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Settings, Cpu, Palette, Key, Database, Save, X } from "lucide-react"
import { useTheme } from "@/components/ThemeProvider"

interface SettingsState {
    ollamaModel: string
    temperature: number
    maxTokens: number
    apiEndpoint: string
}

interface SettingsPanelProps {
    open: boolean
    onOpenChange: (open: boolean) => void
}

export function SettingsPanel({ open, onOpenChange }: SettingsPanelProps) {
    const { theme, setTheme } = useTheme()
    const [settings, setSettings] = useState<SettingsState>({
        ollamaModel: "llama3",
        temperature: 0.7,
        maxTokens: 4000,
        apiEndpoint: "http://localhost:8000",
    })
    const [isSaved, setIsSaved] = useState(false)

    // Load settings from localStorage on mount
    useEffect(() => {
        if (typeof window === "undefined") return
        
        const savedSettings = localStorage.getItem("cpgagent-settings")
        if (savedSettings) {
            try {
                const saved = JSON.parse(savedSettings)
                setSettings({
                    ollamaModel: saved.ollamaModel || "llama3",
                    temperature: saved.temperature || 0.7,
                    maxTokens: saved.maxTokens || 4000,
                    apiEndpoint: saved.apiEndpoint || "http://localhost:8000",
                })
            } catch (e) {
                console.error("Failed to load settings:", e)
            }
        }
    }, [])

    const handleSave = () => {
        if (typeof window === "undefined") return
        // Save settings including theme
        const settingsToSave = { ...settings, theme }
        localStorage.setItem("cpgagent-settings", JSON.stringify(settingsToSave))
        setIsSaved(true)
        setTimeout(() => setIsSaved(false), 2000)
    }

    const handleReset = () => {
        if (typeof window === "undefined") return
        const defaultSettings: SettingsState = {
            ollamaModel: "llama3",
            temperature: 0.7,
            maxTokens: 4000,
            apiEndpoint: "http://localhost:8000",
        }
        setSettings(defaultSettings)
        setTheme("system")
        const settingsToSave = { ...defaultSettings, theme: "system" }
        localStorage.setItem("cpgagent-settings", JSON.stringify(settingsToSave))
    }

    const handleThemeChange = (newTheme: "light" | "dark" | "system") => {
        setTheme(newTheme)
    }

    if (!open) {
        return null
    }

    return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => onOpenChange(false)}>
            <div className="bg-background rounded-lg shadow-lg border border-border dark:border-gray-300/30 w-full max-w-2xl max-h-[75vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
                {/* Header */}
                <div className="border-b border-border p-6 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <Settings className="h-6 w-6 text-primary" />
                        <div>
                            <h2 className="text-2xl font-semibold">Settings</h2>
                            <p className="text-sm text-muted-foreground mt-1">
                                Configure your cpgAgent experience
                            </p>
                        </div>
                    </div>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onOpenChange(false)}
                        className="h-8 w-8"
                    >
                        <X className="h-4 w-4" />
                    </Button>
                </div>

                {/* Settings Content */}
                <div className="flex-1 overflow-y-auto p-6">
                    <div className="space-y-4">
                    
                    {/* AI Model Settings */}
                    <Card>
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <Cpu className="h-5 w-5 text-primary" />
                                <CardTitle>AI Model Configuration</CardTitle>
                            </div>
                            <CardDescription>
                                Configure the local AI model and response parameters
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Ollama Model</label>
                                <select
                                    value={settings.ollamaModel}
                                    onChange={(e) =>
                                        setSettings({ ...settings, ollamaModel: e.target.value })
                                    }
                                    className="w-full px-3 py-2 bg-background border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
                                >
                                    <option value="llama3">Llama 3 (8B) - Recommended</option>
                                    <option value="llama3:70b">Llama 3 (70B) - High Quality</option>
                                    <option value="llama2">Llama 2 (7B) - Faster</option>
                                    <option value="mistral">Mistral (7B) - Alternative</option>
                                    <option value="codellama">CodeLlama - Code-focused</option>
                                </select>
                                <p className="text-xs text-muted-foreground">
                                    Currently using: {settings.ollamaModel}
                                </p>
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">
                                    Temperature: {settings.temperature}
                                </label>
                                <input
                                    type="range"
                                    min="0"
                                    max="1"
                                    step="0.1"
                                    value={settings.temperature}
                                    onChange={(e) =>
                                        setSettings({
                                            ...settings,
                                            temperature: parseFloat(e.target.value),
                                        })
                                    }
                                    className="w-full"
                                />
                                <div className="flex justify-between text-xs text-muted-foreground">
                                    <span>Precise (0.0)</span>
                                    <span>Balanced (0.7)</span>
                                    <span>Creative (1.0)</span>
                                </div>
                            </div>

                            <div className="space-y-2">
                                <label className="text-sm font-medium">Max Response Tokens</label>
                                <Input
                                    type="number"
                                    value={settings.maxTokens}
                                    onChange={(e) =>
                                        setSettings({
                                            ...settings,
                                            maxTokens: parseInt(e.target.value) || 4000,
                                        })
                                    }
                                    min="100"
                                    max="8000"
                                />
                                <p className="text-xs text-muted-foreground">
                                    Controls response length (100-8000 tokens)
                                </p>
                            </div>
                        </CardContent>
                    </Card>

                    {/* API Configuration */}
                    <Card>
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <Database className="h-5 w-5 text-primary" />
                                <CardTitle>Backend Configuration</CardTitle>
                            </div>
                            <CardDescription>
                                Configure the backend API connection
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">API Endpoint</label>
                                <Input
                                    value={settings.apiEndpoint}
                                    onChange={(e) =>
                                        setSettings({ ...settings, apiEndpoint: e.target.value })
                                    }
                                    placeholder="http://localhost:8000"
                                />
                                <p className="text-xs text-muted-foreground">
                                    Backend API URL (restart required to apply)
                                </p>
                            </div>
                        </CardContent>
                    </Card>

                    {/* Appearance */}
                    <Card>
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <Palette className="h-5 w-5 text-primary" />
                                <CardTitle>Appearance</CardTitle>
                            </div>
                            <CardDescription>
                                Customize the look and feel of cpgAgent
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="space-y-2">
                                <label className="text-sm font-medium">Theme</label>
                                <select
                                    value={theme}
                                    onChange={(e) =>
                                        handleThemeChange(e.target.value as "light" | "dark" | "system")
                                    }
                                    className="w-full px-3 py-2 bg-background border border-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
                                >
                                    <option value="light">Light</option>
                                    <option value="dark">Dark</option>
                                    <option value="system">System Default</option>
                                </select>
                                <p className="text-xs text-muted-foreground">
                                    Choose your preferred color theme
                                </p>
                            </div>
                        </CardContent>
                    </Card>

                    {/* API Keys (Optional) */}
                    <Card>
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <Key className="h-5 w-5 text-primary" />
                                <CardTitle>Cloud API Keys (Optional)</CardTitle>
                            </div>
                            <CardDescription>
                                Configure cloud AI providers for production use
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="bg-muted/50 p-4 rounded-lg">
                                <p className="text-sm text-muted-foreground">
                                    ℹ️ You're currently using Ollama locally. Cloud API keys are not
                                    required unless you want to switch to OpenAI or Anthropic.
                                </p>
                            </div>
                            <div className="space-y-2">
                                <label className="text-sm font-medium">OpenAI API Key</label>
                                <Input
                                    type="password"
                                    placeholder="sk-..."
                                    disabled
                                />
                                <p className="text-xs text-muted-foreground">
                                    Configure in backend .env file
                                </p>
                            </div>
                        </CardContent>
                    </Card>

                    {/* System Info */}
                    <Card>
                        <CardHeader>
                            <CardTitle>System Information</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-2 text-sm">
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">Version:</span>
                                <span className="font-medium">1.0.0-beta</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">AI Backend:</span>
                                <span className="font-medium">Ollama (Local)</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">Model:</span>
                                <span className="font-medium">{settings.ollamaModel}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-muted-foreground">API Status:</span>
                                <span className="font-medium text-green-600">Connected</span>
                            </div>
                        </CardContent>
                    </Card>

                    {/* Save/Reset Buttons */}
                    <div className="flex gap-3 justify-end pt-4">
                        <Button variant="outline" onClick={handleReset}>
                            Reset to Defaults
                        </Button>
                        <Button onClick={handleSave} className="gap-2">
                            <Save className="h-4 w-4" />
                            {isSaved ? "Saved!" : "Save Settings"}
                        </Button>
                    </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
