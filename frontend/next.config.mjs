/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    // The browser never talks to the API directly, so the API key/origin never
    // reaches the client and there is no CORS preflight in production.
    const api = process.env.API_BASE_URL ?? "http://localhost:8080";
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
};
export default nextConfig;
