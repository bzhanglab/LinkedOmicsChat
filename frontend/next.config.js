/** @type {import('next').NextConfig} */
const nextConfig = {
    reactStrictMode: true,
    swcMinify: true,
    output: 'standalone', // Required for Docker deployment
    images: {
        domains: [],
    },
}

module.exports = nextConfig
