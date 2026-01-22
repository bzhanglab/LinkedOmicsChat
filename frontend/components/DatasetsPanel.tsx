"use client"

import { useState, useEffect } from "react"
import { Search, Filter, Database as DatabaseIcon } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
import { datasetsAPI, type Dataset } from "@/lib/api"

export function DatasetsPanel() {
    const [datasets, setDatasets] = useState<Dataset[]>([])
    const [loading, setLoading] = useState(true)
    const [searchQuery, setSearchQuery] = useState("")

    useEffect(() => {
        loadDatasets()
    }, [])

    const loadDatasets = async () => {
        try {
            setLoading(true)
            const data = await datasetsAPI.list()
            setDatasets(data)
        } catch (error) {
            console.error("Error loading datasets:", error)
        } finally {
            setLoading(false)
        }
    }

    const filteredDatasets = datasets.filter(
        (dataset) =>
            dataset.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            dataset.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
            dataset.cancer_type?.toLowerCase().includes(searchQuery.toLowerCase())
    )

    return (
        <div className="h-full flex flex-col bg-background">
            {/* Header */}
            <div className="border-b border-border p-6">
                <h2 className="text-2xl font-semibold">Datasets</h2>
                <p className="text-sm text-muted-foreground mt-1">
                    Browse and search multi-omics datasets
                </p>
            </div>

            {/* Search and Filters */}
            <div className="p-6 border-b border-border">
                <div className="flex gap-2">
                    <div className="relative flex-1">
                        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                        <Input
                            placeholder="Search datasets..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="pl-10"
                        />
                    </div>
                    <Button variant="outline">
                        <Filter className="h-4 w-4 mr-2" />
                        Filters
                    </Button>
                </div>
            </div>

            {/* Datasets List */}
            <ScrollArea className="flex-1">
                <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {loading ? (
                        <p className="text-muted-foreground">Loading datasets...</p>
                    ) : filteredDatasets.length === 0 ? (
                        <p className="text-muted-foreground">No datasets found</p>
                    ) : (
                        filteredDatasets.map((dataset) => (
                            <Card key={dataset.id} className="hover:shadow-lg transition-shadow">
                                <CardHeader>
                                    <div className="flex items-start gap-3">
                                        <div className="p-2 bg-primary/10 rounded-lg">
                                            <DatabaseIcon className="h-5 w-5 text-primary" />
                                        </div>
                                        <div className="flex-1">
                                            <CardTitle className="text-lg">{dataset.name}</CardTitle>
                                            <CardDescription className="mt-1">
                                                {dataset.source} • {dataset.cancer_type || "Multiple cancer types"}
                                            </CardDescription>
                                        </div>
                                    </div>
                                </CardHeader>
                                <CardContent>
                                    <p className="text-sm text-muted-foreground mb-4">
                                        {dataset.description}
                                    </p>
                                    <div className="flex flex-wrap gap-2 mb-4">
                                        {dataset.data_types.map((type) => (
                                            <span
                                                key={type}
                                                className="px-2 py-1 bg-secondary text-secondary-foreground text-xs rounded-md"
                                            >
                                                {type}
                                            </span>
                                        ))}
                                    </div>
                                    <div className="flex justify-between text-sm">
                                        <span className="text-muted-foreground">
                                            {dataset.sample_count.toLocaleString()} samples
                                        </span>
                                        <span className="text-muted-foreground">
                                            {dataset.feature_count.toLocaleString()} features
                                        </span>
                                    </div>
                                </CardContent>
                            </Card>
                        ))
                    )}
                </div>
            </ScrollArea>
        </div>
    )
}
