/** @type {import('next').NextConfig} */
const { version } = require("./package.json")

const internalApiOrigin = (process.env.INTERNAL_API_URL || (
    process.env.NODE_ENV === "development"
        ? "http://localhost:8000"
        : "http://backend:8000"
)).replace(/\/+$/, "")

const nextConfig = {
    env: {
        NEXT_PUBLIC_APP_VERSION: version,
    },
    reactStrictMode: true,
    swcMinify: true,
    output: 'standalone', // Required for Docker deployment
    images: {
        domains: [],
    },
    async rewrites() {
        return [
            {
                source: "/api/:path*",
                destination: `${internalApiOrigin}/api/:path*`,
            },
        ]
    },
}

module.exports = nextConfig
