/**
 * Shared types for the code-driven pipeline (discovery, fetch, extract, screen).
 */

/** Call one MCP tool by its bare name (e.g. `record_discovery_coverage`). */
export type McpCall = (tool: string, args: Record<string, unknown>) => Promise<{ content: string; isError: boolean }>;

/** Where a candidate posting came from. */
export type DiscoveryChannel = 'dork' | 'direct' | 'feed';

/** One discovered posting URL awaiting screening. */
export interface Candidate {
  url: string;
  title: string;
  channel: DiscoveryChannel;
  /** Names of the profiles whose search produced this URL. */
  profiles: string[];
}
