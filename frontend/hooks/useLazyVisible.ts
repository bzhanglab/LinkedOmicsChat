import { useRef, useState, useEffect } from "react"

/**
 * Returns a ref to attach to a container element and a boolean `isVisible`
 * that becomes true once the element scrolls within `rootMargin` of the viewport.
 * After becoming visible it stays true (one-shot observer).
 */
export function useLazyVisible(rootMargin = "200px") {
    const ref = useRef<HTMLDivElement>(null)
    const [isVisible, setIsVisible] = useState(false)

    useEffect(() => {
        const el = ref.current
        if (!el) return
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    setIsVisible(true)
                    observer.disconnect()
                }
            },
            { rootMargin }
        )
        observer.observe(el)
        return () => observer.disconnect()
    }, [rootMargin])

    return { ref, isVisible }
}
