"use client"

import Image from "next/image"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ArrowLeft, MessageSquare, Database, BarChart3, Workflow, Cpu } from "lucide-react"
import Link from "next/link"

export default function DocsPage() {
    return (
        <div className="min-h-screen bg-background">
            <div className="max-w-4xl mx-auto p-6 space-y-6">
                {/* Header */}
                <div className="flex items-center gap-4">
                    <Link href="/">
                        <Button variant="ghost" size="icon">
                            <ArrowLeft className="h-4 w-4" />
                        </Button>
                    </Link>
                    <div className="flex items-center gap-4">
                        <div className="relative">
                            {/* Light mode logo */}
                            <Image 
                                src="/cpgagent.png"
                                alt="cpgAgent Logo" 
                                width={200}
                                height={60}
                                className="h-12 w-auto dark:hidden"
                                priority
                            />
                            {/* Dark mode logo */}
                            <Image 
                                src="/cpgagent-dark.png"
                                alt="cpgAgent Logo" 
                                width={200}
                                height={60}
                                className="h-12 w-auto hidden dark:block"
                                priority
                            />
                        </div>
                        <div>
                            <h1 className="text-3xl font-bold">Documentation</h1>
                            <p className="text-muted-foreground mt-1">
                                AI-powered platform for multi-omics analysis
                            </p>
                        </div>
                    </div>
                </div>

                {/* Quick Start */}
                <Card>
                    <CardHeader>
                        <CardTitle>Quick Start</CardTitle>
                        <CardDescription>
                            Get started with cpgAgent in minutes
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                        <p className="text-sm">
                            cpgAgent is an AI-powered platform that helps researchers analyze
                            multi-omics data through natural language queries. Simply ask questions
                            about genes, proteins, pathways, or differential expression, and our AI
                            agents will handle the analysis.
                        </p>
                        <div className="space-y-2">
                            <h3 className="font-semibold text-sm">Key Features:</h3>
                            <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                                <li>Natural language queries for complex analyses</li>
                                <li>Multi-omics data integration (TCGA, CPTAC)</li>
                                <li>Automated correlation and pathway enrichment</li>
                                <li>Differential expression analysis</li>
                                <li>Interactive visualizations</li>
                            </ul>
                        </div>
                    </CardContent>
                </Card>

                {/* Main Features */}
                <div className="grid gap-4 md:grid-cols-2">
                    <Card>
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <MessageSquare className="h-5 w-5 text-primary" />
                                <CardTitle>Chat Interface</CardTitle>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <p className="text-sm text-muted-foreground">
                                Ask questions in natural language. The AI understands your research
                                questions and coordinates specialized agents to perform analyses.
                            </p>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <Database className="h-5 w-5 text-primary" />
                                <CardTitle>Datasets</CardTitle>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <p className="text-sm text-muted-foreground">
                                Browse and search available datasets from TCGA and CPTAC. Filter
                                by cancer type, data type, and sample characteristics.
                            </p>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <BarChart3 className="h-5 w-5 text-primary" />
                                <CardTitle>Visualizations</CardTitle>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <p className="text-sm text-muted-foreground">
                                View generated plots and figures from your analyses. Export
                                visualizations for presentations and publications.
                            </p>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardHeader>
                            <div className="flex items-center gap-2">
                                <Workflow className="h-5 w-5 text-primary" />
                                <CardTitle>Workflows</CardTitle>
                            </div>
                        </CardHeader>
                        <CardContent>
                            <p className="text-sm text-muted-foreground">
                                Execute predefined analysis workflows for common research tasks.
                                Customize parameters and track execution progress.
                            </p>
                        </CardContent>
                    </Card>
                </div>

                {/* Example Queries */}
                <Card>
                    <CardHeader>
                        <CardTitle>Example Queries</CardTitle>
                        <CardDescription>
                            Try these example questions to get started
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                        <div className="space-y-2">
                            <p className="text-sm font-medium">Gene Correlation:</p>
                            <p className="text-sm text-muted-foreground italic">
                                "Find genes correlated with TP53 in breast cancer"
                            </p>
                        </div>
                        <div className="space-y-2">
                            <p className="text-sm font-medium">Pathway Enrichment:</p>
                            <p className="text-sm text-muted-foreground italic">
                                "Perform pathway enrichment for these genes: TP53, BRCA1, MDM2"
                            </p>
                        </div>
                        <div className="space-y-2">
                            <p className="text-sm font-medium">Differential Expression:</p>
                            <p className="text-sm text-muted-foreground italic">
                                "Compare gene expression between stage I and stage IV samples"
                            </p>
                        </div>
                    </CardContent>
                </Card>

                {/* AI Configuration */}
                <Card>
                    <CardHeader>
                        <div className="flex items-center gap-2">
                            <Cpu className="h-5 w-5 text-primary" />
                            <CardTitle>AI Configuration</CardTitle>
                        </div>
                        <CardDescription>
                            Configure your AI model settings
                        </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-3">
                        <p className="text-sm text-muted-foreground">
                            cpgAgent uses local AI models via Ollama by default. You can configure
                            the model, temperature, and other parameters in the Settings panel.
                        </p>
                        <div className="space-y-2">
                            <h3 className="font-semibold text-sm">Recommended Models:</h3>
                            <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
                                <li>Llama 3 (8B) - Balanced performance and speed</li>
                                <li>Llama 3 (70B) - Higher quality, slower</li>
                                <li>Mistral - Alternative option</li>
                            </ul>
                        </div>
                    </CardContent>
                </Card>

                {/* Back Button */}
                <div className="flex justify-center pt-4">
                    <Link href="/">
                        <Button>Back to Application</Button>
                    </Link>
                </div>
            </div>
        </div>
    )
}
