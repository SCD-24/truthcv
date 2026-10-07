/**
 * Shared types for the code-driven pipeline (discovery, fetch, extract, screen).
 */

/** Call one MCP tool by its bare name (e.g. `record_discovery_coverage`). */
export type McpCall = (tool: string, args: Record<string, unknown>) => Promise<{ content: string; isError: boolean }>;

/** Where a candidate posting came from. */
export type DiscoveryChannel = 'dork' | 'direct' | 'feed';

/** A discovery source (board, dork source or feed) that surfaced a posting. */
export interface CandidateSource {
  source: string;
  channel: DiscoveryChannel;
}

/** One discovered posting URL awaiting screening. */
export interface Candidate {
  url: string;
  title: string;
  channel: DiscoveryChannel;
  /** Names of the profiles whose search produced this URL. */
  profiles: string[];
  /** Every distinct source that surfaced this URL (unique by source name). */
  sources: CandidateSource[];
}

/** Why the server dropped a URL before screening. */
export type DroppedReason = 'previously_screened' | 'not_a_posting' | 'duplicate';

/** A discovered URL removed by `filter_unscreened_urls`, with the sources that found it. */
export interface DroppedUrl {
  url: string;
  reason: DroppedReason;
  duplicate_of?: string;
  sources: CandidateSource[];
}
