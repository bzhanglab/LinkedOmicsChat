/** @type {import('next').NextConfig} */
const { version } = require("./package.json")

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
}

module.exports = nextConfig
