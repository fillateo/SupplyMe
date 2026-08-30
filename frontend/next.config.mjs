/** @type {import('next').NextConfig} */
const nextConfig = {
  // Traces the server's real imports into .next/standalone, which is what the
  // Cloud Run image runs. See ../frontend/Dockerfile.
  output: "standalone",
};

// The /api/* proxy is a route handler, not a rewrite: rewrites are resolved at
// build time, and which API to talk to is a property of the deployment. See
// app/api/[...path]/route.ts.
export default nextConfig;
