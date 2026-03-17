"use client"

import { useEffect, useState } from "react"
import { Settings, Cpu, Palette, Key, Database, X } from "lucide-react"
import { useTheme } from "@/components/ThemeProvider"
import { Button } from "@/components/ui/button"
import { authAPI, type PublicRuntimeConfig } from "@/lib/auth"

interface SettingsPanelProps {
    open: boolean
    onOpenChange: (open: boolean) => void
}

function InfoRow({ label, value }: { label: string; value: string }) {
    return (
        <div className="flex justify-between items-center py-1.5">
            <span className="text-sm text-muted-foreground">{label}</span>
            <span className="text-sm font-medium">{value}</span>
        </div>
    )
}

export function SettingsPanel({ open, onOpenChange }: SettingsPanelProps) {
    const { theme, setTheme } = useTheme()
    const [runtimeConfig, setRuntimeConfig] = useState<PublicRuntimeConfig | null>(null)

    useEffect(() => {
        if (!open) return

        let cancelled = false
        authAPI
            .getPublicRuntimeConfig()
            .then((config) => {
                if (!cancelled) setRuntimeConfig(config)
            })
            .catch((error) => {
                console.error("Failed to load runtime config:", error)
            })

        return () => {
            cancelled = true
        }
    }, [open])

    if (!open) return null

    return (
        <div
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
            onClick={() => onOpenChange(false)}
        >
            <div
                className="bg-background rounded-lg shadow-lg border border-border w-full max-w-lg max-h-[80vh] flex flex-col"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="border-b border-border px-6 py-4 flex items-center justify-between shrink-0">
                    <div className="flex items-center gap-3">
                        <Settings className="h-5 w-5 text-primary" />
                        <h2 className="text-lg font-semibold">Settings</h2>
                    </div>
                    <Button variant="ghost" size="icon" onClick={() => onOpenChange(false)} className="h-8 w-8">
                        <X className="h-4 w-4" />
                    </Button>
                </div>

                {/* Content */}
                <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">

                    {/* Appearance — the only user-editable section */}
                    <section>
                        <div className="flex items-center gap-2 mb-3">
                            <Palette className="h-4 w-4 text-primary" />
                            <h3 className="text-sm font-semibold">Appearance</h3>
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm text-muted-foreground">Theme</label>
                            <div className="grid grid-cols-3 gap-2">
                                {(["light", "dark", "system"] as const).map((t) => (
                                    <button
                                        key={t}
                                        onClick={() => setTheme(t)}
                                        className={[
                                            "px-3 py-2 rounded-md border text-sm font-medium capitalize transition-colors",
                                            theme === t
                                                ? "border-primary bg-primary/10 text-primary"
                                                : "border-border text-muted-foreground hover:border-primary/50 hover:text-foreground",
                                        ].join(" ")}
                                    >
                                        {t === "system" ? "System" : t.charAt(0).toUpperCase() + t.slice(1)}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </section>

                    <div className="border-t border-border" />

                    {/* AI Model — read-only */}
                    <section>
                        <div className="flex items-center gap-2 mb-3">
                            <Cpu className="h-4 w-4 text-muted-foreground" />
                            <h3 className="text-sm font-semibold text-muted-foreground">AI Model</h3>
                            <span className="text-xs text-muted-foreground/60 ml-auto">server-configured</span>
                        </div>
                        <div className="rounded-md bg-muted/40 border border-border px-4 divide-y divide-border">
                            <InfoRow label="Provider" value={runtimeConfig?.llm_provider || "Loading..."} />
                            <InfoRow label="Model" value={runtimeConfig?.llm_model || "Loading..."} />
                            <InfoRow label="Temperature" value={runtimeConfig ? String(runtimeConfig.temperature) : "Loading..."} />
                            <InfoRow label="Max tokens" value={runtimeConfig ? runtimeConfig.max_tokens.toLocaleString("en-US").replace(/,/g, " ") : "Loading..."} />
                        </div>
                    </section>

                    {/* Backend — read-only */}
                    <section>
                        <div className="flex items-center gap-2 mb-3">
                            <Database className="h-4 w-4 text-muted-foreground" />
                            <h3 className="text-sm font-semibold text-muted-foreground">Backend</h3>
                            <span className="text-xs text-muted-foreground/60 ml-auto">server-configured</span>
                        </div>
                        <div className="rounded-md bg-muted/40 border border-border px-4 divide-y divide-border">
                            <InfoRow label="API endpoint" value={process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"} />
                            <InfoRow label="Architecture" value={runtimeConfig?.architecture || "Loading..."} />
                            <InfoRow label="Orchestration" value={runtimeConfig?.orchestration || "Loading..."} />
                        </div>
                    </section>

                    {/* API Keys — read-only */}
                    <section>
                        <div className="flex items-center gap-2 mb-3">
                            <Key className="h-4 w-4 text-muted-foreground" />
                            <h3 className="text-sm font-semibold text-muted-foreground">API Keys</h3>
                            <span className="text-xs text-muted-foreground/60 ml-auto">set in .env</span>
                        </div>
                        <div className="rounded-md bg-muted/40 border border-border px-4 divide-y divide-border">
                            <InfoRow label="GOOGLE_API_KEY" value="••••••••••••" />
                            <InfoRow label="NCBI_API_KEY" value="••••••••••••" />
                        </div>
                        <p className="text-xs text-muted-foreground mt-2">
                            Keys are configured in the backend <code className="font-mono">.env</code> file and cannot be changed here.
                        </p>
                    </section>

                    {/* System info — read-only */}
                    <section>
                        <h3 className="text-sm font-semibold text-muted-foreground mb-3">System</h3>
                        <div className="rounded-md bg-muted/40 border border-border px-4 divide-y divide-border">
                            <InfoRow label="Version" value="1.0.0-beta" />
                            <InfoRow label="Data sources" value="LinkedOmics · GDC · CPTAC" />
                            <InfoRow label="API status" value="Connected" />
                        </div>
                    </section>

                </div>
            </div>
        </div>
    )
}
