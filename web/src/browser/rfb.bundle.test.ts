// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { build } from "vite";
import type { Plugin, Rollup } from "vite";

// Vitest runs from the web/ package root, where the Vite config lives.
const entryPath = "src/browser/rfb.bundle.test.ts";
const exposedKey = "__rfbBundleClass";

/** Consumer shape of BrowserSessionPage: a default import of the RFB module,
 * called to resolve the class, and published on `globalThis` because app-mode
 * builds drop entry exports. */
const consumerSource = `import getRfb from "./rfb"; (globalThis as Record<string, unknown>).${exposedKey} = getRfb();`;

/** Serves `consumerSource` under this file's own id. The id must be a real
 * file: Rolldown picks the CommonJS interop mode from the importing file, and
 * a nonexistent id does not reproduce the production shape. */
function consumerEntry(): Plugin {
  return {
    name: "rfb-bundle-consumer",
    enforce: "pre",
    load: (id) => (id.split("?")[0].endsWith(entryPath) ? consumerSource : null),
  };
}

/** Builds the consumer in app mode with the repo's own Vite config (plugins
 * and Rolldown interop included), the way the production build does, and
 * returns the emitted entry chunk. Nothing is written to disk. */
async function buildConsumerBundle(): Promise<string> {
  const result = (await build({
    configFile: "vite.config.ts",
    logLevel: "silent",
    plugins: [consumerEntry()],
    build: { write: false, minify: false, rollupOptions: { input: entryPath } },
  })) as Rollup.RollupOutput | Rollup.RollupOutput[];
  const chunk = [result].flat().flatMap((output) => output.output).find((item) => item.type === "chunk" && item.isEntry);
  if (chunk?.type !== "chunk") throw new Error("rfb bundle produced no entry chunk");
  return chunk.code;
}

/** Runs ES module source with Node's own loader. Vitest's module runner is
 * bypassed on purpose: the point is to run the emitted bundle untouched. */
function runSource(code: string): Promise<unknown> {
  return import(/* @vite-ignore */ `data:text/javascript;base64,${btoa(code)}`);
}

describe("rfb production bundle", () => {
  afterEach(() => {
    delete (globalThis as Record<string, unknown>)[exposedKey];
  });

  it("exposes the real RFB class to a default-importing consumer", async () => {
    await runSource(await buildConsumerBundle());

    const rfb = (globalThis as Record<string, unknown>)[exposedKey] as { prototype: object };
    expect(typeof rfb).toBe("function");
    expect(typeof (rfb.prototype as { disconnect?: unknown }).disconnect).toBe("function");
    expect(typeof (rfb.prototype as { addEventListener?: unknown }).addEventListener).toBe("function");
  });
});
