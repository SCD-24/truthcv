// `@novnc/novnc` is pinned to an EXACT 1.6.0 in package.json (no caret) —
// 1.7.0's package.json restricts `exports` to `./core/rfb.js` only, which
// breaks this `lib/rfb` subpath entirely (Vite's resolver fails before this
// module even loads). Do not loosen the pin or bump the version without
// re-checking that `@novnc/novnc/lib/rfb` still resolves.
import RfbModule from "@novnc/novnc/lib/rfb";

type RfbConstructor = typeof RfbModule;

/** The value under `default` on an object, or undefined for anything else. */
function defaultOf(value: unknown): unknown {
  if (value === null || typeof value !== "object") return undefined;
  return (value as { default?: unknown }).default;
}

/** Unwraps the noVNC RFB class from whichever CommonJS interop shape the
 * bundler produced: the class itself, `{ default: Class }`, or
 * `{ default: { default: Class } }` (an `__esModule` wrapper). Throws if the
 * module holds no constructor in any of those shapes. */
export function unwrapRfbConstructor(mod: unknown): RfbConstructor {
  const candidates = [mod, defaultOf(mod), defaultOf(defaultOf(mod))];
  const found = candidates.find(
    (candidate): candidate is RfbConstructor => typeof candidate === "function"
  );
  if (!found) {
    throw new Error(
      "noVNC RFB constructor not found: expected a class, { default: class }, or { default: { default: class } }"
    );
  }
  return found;
}

let resolved: RfbConstructor | undefined;

/** The noVNC `RFB` class, resolved past any bundler interop wrapper. Resolved
 * on first call rather than at import, so a resolution failure surfaces to the
 * caller instead of breaking module load. */
export default function getRfb(): RfbConstructor {
  resolved ??= unwrapRfbConstructor(RfbModule);
  return resolved;
}

/** An instance of the noVNC `RFB` class. */
export type RFB = InstanceType<RfbConstructor>;
