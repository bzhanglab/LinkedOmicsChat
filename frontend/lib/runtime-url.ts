const LOCAL_API_URL = "http://localhost:8000"

function trimTrailingSlash(value: string | undefined): string {
    return (value || "").trim().replace(/\/+$/, "")
}

function isLocalHost(hostname: string): boolean {
    return hostname === "localhost" || hostname === "127.0.0.1"
}

/**
 * Resolve the backend base URL at runtime.
 * Local development defaults to localhost:8000; hosted deployments default to
 * same-origin requests so HTTPS sites do not downgrade API calls to plain HTTP.
 */
export function resolveApiUrl(): string {
    const configuredUrl = trimTrailingSlash(process.env.NEXT_PUBLIC_API_URL)

    if (typeof window === "undefined") {
        return configuredUrl
    }

    const { hostname, protocol } = window.location
    const onLocalHost = isLocalHost(hostname)

    if (protocol === "https:" && configuredUrl.startsWith("http://") && !onLocalHost) {
        return ""
    }

    if (configuredUrl) {
        return configuredUrl
    }

    if (onLocalHost) {
        return LOCAL_API_URL
    }

    return ""
}

export function describeApiUrl(): string {
    return resolveApiUrl() || "same-origin (/api/...)"
}
