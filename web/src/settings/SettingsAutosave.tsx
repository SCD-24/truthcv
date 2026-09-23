import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

/** Typed edits wait briefly; blur and modal close flush immediately. */
export const SETTINGS_AUTOSAVE_DELAY_MS = 500;
export type SaveStatus = "idle" | "pending" | "saving" | "saved" | "error" | "invalid";
type Entry = {
  revision: number;
  value: unknown;
  write: (value: never) => Promise<void>;
  status: SaveStatus;
  error: string | null;
  timer?: ReturnType<typeof setTimeout>;
};

/** One coordinator per Settings session: the server's routing read/merge/write
 * must not receive overlapping requests from different picker rows. */
export class SettingsAutosaveCoordinator {
  private entries = new Map<string, Entry>();
  private listeners = new Set<() => void>();
  private active: Promise<void> | null = null;
  private disposed = false;
  private discarding = false;
  private nextRevision = 0;

  subscribe = (listener: () => void) => {
    this.revive();
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  private notify() { if (!this.disposed) this.listeners.forEach((listener) => listener()); }

  status(key: string): { status: SaveStatus; error: string | null } {
    const entry = this.entries.get(key);
    return { status: entry?.status ?? "idle", error: entry?.error ?? null };
  }

  edit<T>(key: string, value: T, write: (value: T) => Promise<void>, options: {
    valid?: boolean; debounce?: boolean;
  } = {}) {
    if (this.disposed || this.discarding) return;
    const previous = this.entries.get(key);
    if (previous?.timer) clearTimeout(previous.timer);
    const entry: Entry = {
      revision: ++this.nextRevision,
      value,
      write: write as (value: never) => Promise<void>,
      status: options.valid === false ? "invalid" : "pending",
      error: null,
    };
    this.entries.set(key, entry);
    if (entry.status === "pending") {
      if (options.debounce) {
        entry.timer = setTimeout(() => { entry.timer = undefined; this.pump(); }, SETTINGS_AUTOSAVE_DELAY_MS);
      } else this.pump();
    }
    this.notify();
  }

  flush(key?: string) {
    if (this.discarding) return;
    for (const [name, entry] of this.entries) {
      if (key && key !== name) continue;
      if (entry.timer) { clearTimeout(entry.timer); entry.timer = undefined; }
    }
    this.pump();
  }

  retry(key: string) {
    const entry = this.entries.get(key);
    if (this.discarding || entry?.status !== "error") return;
    entry.status = "pending";
    entry.error = null;
    this.notify();
    this.pump();
  }

  /** Discard queued drafts before waiting: an active server write cannot be undone. */
  discard() {
    this.discarding = true;
    for (const entry of this.entries.values()) if (entry.timer) clearTimeout(entry.timer);
    this.entries.clear();
    this.notify();
  }

  async discardAndWait() {
    this.discard();
    while (this.active) await this.active;
  }

  cancel(key: string) {
    const entry = this.entries.get(key);
    if (entry?.timer) clearTimeout(entry.timer);
    this.entries.delete(key);
    this.notify();
  }

  async flushAndWait(): Promise<boolean> {
    this.flush();
    while (this.active) await this.active;
    return ![...this.entries.values()].some((e) =>
      e.status === "error" || e.status === "invalid" || e.status === "pending" || e.status === "saving",
    );
  }

  private pump() {
    if (this.disposed || this.discarding || this.active) return;
    const next = [...this.entries].find(([, e]) => e.status === "pending" && !e.timer);
    if (!next) return;
    const [key, entry] = next;
    const revision = entry.revision;
    entry.status = "saving";
    this.notify();
    this.active = Promise.resolve().then(() => entry.write(entry.value as never))
      .then(() => {
        const current = this.entries.get(key);
        if (current?.revision === revision) current.status = "saved";
      }, (error: unknown) => {
        const current = this.entries.get(key);
        if (current?.revision === revision) {
          current.status = "error";
          current.error = error instanceof Error ? error.message : "Couldn't save setting.";
        }
      }).finally(() => {
        this.active = null;
        this.notify();
        this.pump();
      });
  }

  /** React StrictMode replays effect cleanup/setup on the same coordinator. */
  revive() {
    this.disposed = false;
    this.discarding = false;
  }

  dispose() {
    this.disposed = true;
    this.entries.forEach((entry) => { if (entry.timer) clearTimeout(entry.timer); });
    this.entries.clear();
    this.listeners.clear();
  }
}

const AutosaveContext = createContext<SettingsAutosaveCoordinator | null>(null);
export function useHasSettingsAutosaveProvider() { return useContext(AutosaveContext) !== null; }
export function SettingsAutosaveProvider({ children }: { children: ReactNode }) {
  const [coordinator] = useState(() => new SettingsAutosaveCoordinator());
  useEffect(() => {
    coordinator.revive();
    return () => coordinator.dispose();
  }, [coordinator]);
  return <AutosaveContext.Provider value={coordinator}>{children}</AutosaveContext.Provider>;
}

/** Sections rendered alone still share a coordinator among their own rows. */
export function useSettingsAutosaveCoordinator() {
  const shared = useContext(AutosaveContext);
  const local = useRef<SettingsAutosaveCoordinator | null>(null);
  if (!shared && !local.current) local.current = new SettingsAutosaveCoordinator();
  useEffect(() => {
    const coordinator = local.current;
    coordinator?.revive();
    return () => coordinator?.dispose();
  }, []);
  return shared ?? local.current!;
}

/** Only edit() represents a user action: subscribing or mounting never writes. */
export function useSettingsAutosave(key: string) {
  const coordinator = useSettingsAutosaveCoordinator();
  const [state, setState] = useState(() => coordinator.status(key));
  useEffect(() => coordinator.subscribe(() => setState(coordinator.status(key))), [coordinator, key]);
  return { ...state, edit: <T,>(value: T, write: (v: T) => Promise<void>, options?: {
    valid?: boolean; debounce?: boolean;
  }) => coordinator.edit(key, value, write, options),
  flush: () => coordinator.flush(key), retry: () => coordinator.retry(key),
  cancel: () => coordinator.cancel(key) };
}
