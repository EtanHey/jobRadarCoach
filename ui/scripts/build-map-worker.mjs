import { build } from "esbuild";
import { fileURLToPath } from "node:url";
// MapLibre 6's worker imports a sibling module. Next's URL asset loader only
// copies the entry file, so bundle it before Next fingerprints/serves the asset.
await build({
  entryPoints: [fileURLToPath(import.meta.resolve("maplibre-gl/dist/maplibre-gl-worker.mjs"))],
  outfile: fileURLToPath(new URL("../lib/generated/maplibre-worker.mjs", import.meta.url)),
  bundle: true, format: "esm", platform: "browser", minify: true,
});
