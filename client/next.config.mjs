// The Mac page is exported as plain files (client/out) that the Open Dots server
// serves on its own address, next to the iPhone app and the API. Nothing here
// may need a Next.js server at runtime.
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'export',
};

export default nextConfig;
