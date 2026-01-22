"use client"

import { createContext, useContext, useEffect, useState } from "react"

type Theme = "light" | "dark" | "system"

interface ThemeContextType {
    theme: Theme
    setTheme: (theme: Theme) => void
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

export function ThemeProvider({ children }: { children: React.ReactNode }) {
    const [theme, setTheme] = useState<Theme>("system")
    const [mounted, setMounted] = useState(false)

    useEffect(() => {
        setMounted(true)
        // Load theme from localStorage
        const savedSettings = localStorage.getItem("cpgagent-settings")
        if (savedSettings) {
            try {
                const settings = JSON.parse(savedSettings)
                setTheme(settings.theme || "system")
            } catch (e) {
                console.error("Failed to load theme:", e)
            }
        }
    }, [])

    useEffect(() => {
        if (!mounted) return

        const root = document.documentElement
        
        // Remove both classes first
        root.classList.remove("light", "dark")

        if (theme === "system") {
            const systemTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
                ? "dark"
                : "light"
            root.classList.add(systemTheme)
        } else {
            root.classList.add(theme)
        }
    }, [theme, mounted])

    // Listen for system theme changes when using system theme
    useEffect(() => {
        if (theme !== "system") return

        const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")
        const handleChange = () => {
            const root = document.documentElement
            root.classList.remove("light", "dark")
            root.classList.add(mediaQuery.matches ? "dark" : "light")
        }

        mediaQuery.addEventListener("change", handleChange)
        return () => mediaQuery.removeEventListener("change", handleChange)
    }, [theme])

    return (
        <ThemeContext.Provider value={{ theme, setTheme }}>
            {children}
        </ThemeContext.Provider>
    )
}

export function useTheme() {
    const context = useContext(ThemeContext)
    if (context === undefined) {
        throw new Error("useTheme must be used within a ThemeProvider")
    }
    return context
}
