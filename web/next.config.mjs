/** @type {import('next').NextConfig} */
const nextConfig = {
  // The JSON snapshot is read at runtime via fs; trace it into serverless bundles.
  experimental: {
    outputFileTracingIncludes: {
      "/api/**": ["./data/**"],
    },
  },
};
export default nextConfig;
