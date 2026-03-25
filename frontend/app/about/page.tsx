import type { Metadata } from "next"
import { AboutContent } from "./AboutContent"

export const metadata: Metadata = {
    title: "About — LinkedOmicsChat",
    description: "About LinkedOmicsChat: an AI-powered conversational interface for multi-omics cancer research.",
}

export default function AboutPage() {
    return <AboutContent />
}
