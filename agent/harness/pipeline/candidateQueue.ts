/**
 * A growable FIFO of candidates: producers `push` batches and `close` when
 * done; consumers `take` the next candidate and wait while the queue is empty
 * but still open.
 */
import type { Candidate } from './types.js';

/** Growable candidate queue (single consumer group; each candidate is taken once). */
export class CandidateQueue {
  private items: Candidate[];
  private next = 0;
  private open: boolean;
  private waiters: Array<() => void> = [];

  /**
   * @param initial Candidates already known.
   * @param open Whether more candidates may still be pushed.
   */
  constructor(initial: Candidate[] = [], open = true) {
    this.items = [...initial];
    this.open = open;
  }

  /** Whether more candidates may still arrive. */
  get isOpen(): boolean {
    return this.open;
  }

  /** Total candidates ever queued. */
  get size(): number {
    return this.items.length;
  }

  /** Add a batch (ignored once closed) and wake waiting consumers. */
  push(batch: Candidate[]): void {
    if (!this.open) return;
    this.items.push(...batch);
    this.wake();
  }

  /** Mark the queue complete; waiting consumers finish once it drains. */
  close(): void {
    this.open = false;
    this.wake();
  }

  /** The next candidate, or undefined when the queue is closed and drained. */
  async take(): Promise<Candidate | undefined> {
    while (this.next >= this.items.length) {
      if (!this.open) return undefined;
      await new Promise<void>((resolve) => this.waiters.push(resolve));
    }
    return this.items[this.next++];
  }

  private wake(): void {
    const ws = this.waiters;
    this.waiters = [];
    for (const w of ws) w();
  }
}
