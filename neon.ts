import { defineConfig } from "@neon/config/v1";

export default defineConfig({
  // Declare your Neon services here
  auth: true,
  // Neon CLI rejects AI Gateway on Free. Preserve direct Gemini generation.
  aiGateway: false,
  functions: {
    hello: {
      name: "Knowra source integrity",
      source: "./hello.ts",
      env: { ORIGIN_SECRET: process.env.KNOWRA_FUNCTION_SECRET! },
    },
  },
  buckets: {
    // "private" is the default; use "public_read" for anonymous reads
    assets: { access: "private" },
  },
  // Branch policy: per-branch tuning
  branch: (branch) => {
    if (branch.isDefault) {
      // Default branch: no overrides, uses project defaults
      return {};
    }
    if (!branch.exists) {
      // New non-default branches: auto-expire
      // Run `neon checkout <name>` to create a new branch with these settings
      return { ttl: "7d" };
    }
    // Existing branch: no changes
    return {};
  },
});
