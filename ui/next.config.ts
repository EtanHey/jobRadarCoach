import type { NextConfig } from "next";

// NEXT_PUBLIC_* values are inlined into client JavaScript at build time, so a secret Logo.dev key must stop the build.
const logoDevKey = process.env.NEXT_PUBLIC_LOGO_DEV_KEY;
if (logoDevKey && !logoDevKey.startsWith("pk_")) {
  throw new Error("NEXT_PUBLIC_LOGO_DEV_KEY must be a Logo.dev publishable pk_ key; refusing to inline any other key into client JavaScript.");
}

const config: NextConfig = {
  output: process.env.VERCEL ? undefined : "standalone",
  poweredByHeader: false,
};
export default config;
