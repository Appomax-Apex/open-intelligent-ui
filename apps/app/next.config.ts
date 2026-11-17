// Adapted from CopilotKit/OpenIntelligentUI@8391a94 apps/app/next.config.ts (MIT, Copyright (c) Atai Barkai). Changes: NEXT_DIST_DIR picks the build directory, so scripts/run-plan.sh never replaces the build another run is serving.
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  serverExternalPackages: ["@copilotkit/runtime"],
  ...(process.env.NEXT_DIST_DIR && { distDir: process.env.NEXT_DIST_DIR }),
};

export default nextConfig;
