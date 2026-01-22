"use client"

import { BarChart3, TrendingUp, Activity } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"

export function VisualizationsPanel() {
    const mockVisualizations = [
        {
            id: "1",
            title: "Gene Expression Correlation",
            type: "scatter",
            description: "Correlation between TP53 and MDM2 expression",
            timestamp: new Date(),
        },
        {
            id: "2",
            title: "Survival Analysis",
            type: "survival",
            description: "Kaplan-Meier curves for EGFR expression groups",
            timestamp: new Date(),
        },
        {
            id: "3",
            title: "Differential Expression",
            type: "volcano",
            description: "Volcano plot showing DEGs in breast cancer",
            timestamp: new Date(),
        },
    ]

    return (
        <div className="h-full flex flex-col bg-background">
            {/* Header */}
            <div className="border-b border-border p-6">
                <h2 className="text-2xl font-semibold">Visualizations</h2>
                <p className="text-sm text-muted-foreground mt-1">
                    View and manage your analysis visualizations
                </p>
            </div>

            {/* Visualizations Grid */}
            <ScrollArea className="flex-1">
                <div className="p-6">
                    {mockVisualizations.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-64 text-center">
                            <Activity className="h-12 w-12 text-muted-foreground mb-4" />
                            <h3 className="text-lg font-medium">No visualizations yet</h3>
                            <p className="text-sm text-muted-foreground mt-2">
                                Start a conversation or analysis to generate visualizations
                            </p>
                        </div>
                    ) : (
                        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
                            {mockVisualizations.map((viz) => (
                                <Card key={viz.id} className="hover:shadow-lg transition-shadow cursor-pointer">
                                    <CardHeader>
                                        <div className="flex items-start gap-3">
                                            <div className="p-2 bg-primary/10 rounded-lg">
                                                <BarChart3 className="h-5 w-5 text-primary" />
                                            </div>
                                            <div className="flex-1">
                                                <CardTitle className="text-lg">{viz.title}</CardTitle>
                                                <CardDescription className="mt-1">
                                                    {viz.type}
                                                </CardDescription>
                                            </div>
                                        </div>
                                    </CardHeader>
                                    <CardContent>
                                        <div className="aspect-video bg-muted rounded-lg mb-4 flex items-center justify-center">
                                            <TrendingUp className="h-12 w-12 text-muted-foreground" />
                                        </div>
                                        <p className="text-sm text-muted-foreground">
                                            {viz.description}
                                        </p>
                                        <p className="text-xs text-muted-foreground mt-2">
                                            {viz.timestamp.toLocaleDateString()}
                                        </p>
                                    </CardContent>
                                </Card>
                            ))}
                        </div>
                    )}
                </div>
            </ScrollArea>
        </div>
    )
}
