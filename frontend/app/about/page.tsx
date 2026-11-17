import type { Metadata } from "next"
import { AboutContent } from "./AboutContent"

export const metadata: Metadata = {
    title: "About — LinkedOmicsChat",
    description: "About LinkedOmicsChat: a natural-language interface for cancer multi-omics research.",
}

export default function AboutPage() {
    return <AboutContent />
}
