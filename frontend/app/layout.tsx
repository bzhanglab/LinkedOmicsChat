import type { Metadata } from "next"
import { Inter } from "next/font/google"
import "./globals.css"
import { ThemeProvider } from "@/components/ThemeProvider"

const inter = Inter({ subsets: ["latin"] })

export const metadata: Metadata = {
    title: "cpgAgent - Modern Agentic Platform for Multi-Omics",
    description: "AI-powered platform for bioinformatics research and multi-omics analysis",
    keywords: ["bioinformatics", "AI", "omics", "genomics", "proteomics", "research"],
}

export default function RootLayout({
    children,
}: {
    children: React.ReactNode
}) {
    return (
        <html lang="en" suppressHydrationWarning>
            <body className={inter.className}>
                <ThemeProvider>
                    {children}
                </ThemeProvider>
            </body>
        </html>
    )
}
