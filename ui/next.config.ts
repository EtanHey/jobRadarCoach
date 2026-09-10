import type { NextConfig } from "next";
const config: NextConfig = {
  output: process.env.VERCEL ? undefined : "standalone",
  poweredByHeader: false,
};
export default config;
