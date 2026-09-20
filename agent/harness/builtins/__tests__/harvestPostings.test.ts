import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { harvestPostings, harvestPostingsTool, type BrowserToolCall, type BrowserToolResult } from '../harvestPostings.js';

/** A greenhouse-shaped posting link line, as `browser_snapshot` might render it. */
const GREENHOUSE_LINK =
  '- link "Senior Backend Engineer" [ref=e10]: https://boards.greenhouse.io/acme/jobs/123456';
/** A lever-shaped posting link line. */
const LEVER_LINK = '- link "Product Manager" [ref=e11]: https://jobs.lever.co/acme/abc-123-def';
/** An ashby-shaped posting link line. */
const ASHBY_LINK = '- link "Staff Designer" [ref=e12]: https://jobs.ashbyhq.com/acme/xyz-789';
/** A personio-shaped posting link line. */
const PERSONIO_LINK = '- link "Data Analyst" [ref=e13]: https://acme.jobs.personio.de/job/9001';
/** A link whose URL matches no known ATS shape — must never be extracted. */
const UNKNOWN_LINK = '- link "Mystery Role" [ref=e14]: https://example.com/careers/mystery-role';

/** Silence (and reset) the module's `harvest_postings.mode` stderr line
 * around every test, so a real harness run's stderr stays readable — the
 * tests that check the mode line install their own local spy on top. */
beforeEach(() => {
  vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
});
afterEach(() => {
  vi.restoreAllMocks();
});

/** Build a stub {@link BrowserToolCall} from a map of toolName -> canned result
 * (or a function of the call args), recording every call made. */
function stubBrowserCall(
  handlers: Record<string, BrowserToolResult | ((args: Record<string, unknown>) => BrowserToolResult)>,
  calls: { toolName: string; args: Record<string, unknown> }[] = [],
): BrowserToolCall {
  return async (toolName, args) => {
    calls.push({ toolName, args });
    const handler = handlers[toolName];
    if (!handler) return { content: `no stub for ${toolName}`, isError: true };
    return typeof handler === 'function' ? handler(args) : handler;
  };
}

/** A single-board request with no keyword typing needed. */
function board(name: string, url: string): { board: string; url: string } {
  return { board: name, url };
}

/** The standard tab-tool stub set for a single, uncontested board: one tab,
 * index 0, that never closes mid-test. `browser_tab_list` reports the same
 * (parseable) content on every call, including this invocation's own
 * upfront tab-listing probe. */
function singleTabHandlers(snapshotContent: string): Record<string, BrowserToolResult> {
  return {
    browser_tab_new: { content: '[0]', isError: false },
    browser_tab_list: { content: '[0] about:blank', isError: false },
    browser_tab_select: { content: 'ok', isError: false },
    browser_navigate: { content: 'ok', isError: false },
    browser_snapshot: { content: snapshotContent, isError: false },
    browser_tab_close: { content: 'ok', isError: false },
  };
}

/** One tab in {@link fakeTabBrowser}'s in-memory model. */
interface FakeTab {
  index: number;
  url: string;
}

/** Build a stateful fake tab-managing browser, recording every call made.
 * `renderTab` controls the tab-listing line format, so the same fake can
 * exercise both the legacy `[N]` shape and the pinned
 * `@playwright/mcp@0.0.79` `- N: (current) [Title] (https://…)` shape.
 * `snapshotFor` returns the snapshot content for the tab currently selected.
 * Seeded with ONE pre-existing tab (index 0) before any board is harvested,
 * mirroring a real browser session, which always has at least its default
 * tab open — an upfront tab-listing probe against a genuinely EMPTY list
 * would otherwise be indistinguishable from an unparseable one. */
function fakeTabBrowser(
  calls: { toolName: string; args: Record<string, unknown> }[],
  snapshotFor: (tab: FakeTab) => string,
  renderTab: (tab: FakeTab) => string = (t) => `[${t.index}] ${t.url}`,
): BrowserToolCall {
  let tabs: FakeTab[] = [{ index: 0, url: 'about:blank' }];
  let current: number | undefined;
  let nextIndex = 1;
  return async (toolName, args) => {
    calls.push({ toolName, args });
    if (toolName === 'browser_tab_new') {
      const index = nextIndex++;
      tabs.push({ index, url: 'about:blank' });
      return { content: `[${index}]`, isError: false };
    }
    if (toolName === 'browser_tab_list') {
      return { content: tabs.map(renderTab).join('\n'), isError: false };
    }
    if (toolName === 'browser_tab_select') {
      const idx = args.index as number;
      if (!tabs.some((t) => t.index === idx)) return { content: 'no such tab', isError: true };
      current = idx;
      return { content: 'ok', isError: false };
    }
    if (toolName === 'browser_navigate') {
      const tab = tabs.find((t) => t.index === current);
      if (tab) tab.url = args.url as string;
      return { content: 'ok', isError: false };
    }
    if (toolName === 'browser_snapshot') {
      const tab = tabs.find((t) => t.index === current);
      return { content: tab ? snapshotFor(tab) : 'no tab selected', isError: false };
    }
    if (toolName === 'browser_tab_close') {
      const idx = args.index as number;
      tabs = tabs.filter((t) => t.index !== idx);
      return { content: 'ok', isError: false };
    }
    return { content: 'ok', isError: false };
  };
}

describe('harvestPostingsTool definition', () => {
  it('is named harvest_postings and requires boards', () => {
    expect(harvestPostingsTool.name).toBe('harvest_postings');
    expect(harvestPostingsTool.inputSchema.required).toEqual(['boards']);
  });

  it('no longer accepts a location argument', () => {
    const properties = harvestPostingsTool.inputSchema.properties as { boards?: { items?: { properties?: object } } };
    expect(properties.boards?.items?.properties).not.toHaveProperty('location');
  });
});

describe('harvestPostings: postings found (outcome "searched", matches record_discovery_coverage status)', () => {
  it('extracts postings from a stubbed browser tool surface by URL shape', async () => {
    const snapshot = [GREENHOUSE_LINK, LEVER_LINK, ASHBY_LINK, PERSONIO_LINK, UNKNOWN_LINK].join('\n');
    const call = stubBrowserCall(singleTabHandlers(snapshot));

    const result = await harvestPostings({ boards: [board('Acme Careers', 'https://acme.example/jobs')] }, call);

    expect(result.isError).toBe(false);
    const { results } = JSON.parse(result.content);
    expect(results).toHaveLength(1);
    expect(results[0].outcome).toBe('searched');
    expect(results[0].tier).toBe('harvest');
    expect(results[0].postings).toHaveLength(4);
    expect(results[0].postings.map((p: { ats: string }) => p.ats).sort()).toEqual([
      'ashby',
      'greenhouse',
      'lever',
      'personio',
    ]);
    // The unrecognised URL shape is never extracted.
    expect(results[0].postings.some((p: { url: string }) => p.url.includes('mystery-role'))).toBe(false);
  });

  it('de-duplicates the same posting URL seen twice', async () => {
    const snapshot = [GREENHOUSE_LINK, GREENHOUSE_LINK].join('\n');
    const call = stubBrowserCall(singleTabHandlers(snapshot));

    const result = await harvestPostings({ boards: [board('Acme', 'https://acme.example/jobs')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].postings).toHaveLength(1);
  });

  it('extracts real postings even past an incidental reCAPTCHA footer notice', async () => {
    // The standard Google reCAPTCHA footer, present on many ATS board pages,
    // must never suppress genuinely extractable postings on the same page.
    const snapshot = [
      GREENHOUSE_LINK,
      LEVER_LINK,
      'This site is protected by reCAPTCHA and the Google Privacy Policy and Terms of Service apply.',
    ].join('\n');
    const call = stubBrowserCall(singleTabHandlers(snapshot));

    const result = await harvestPostings({ boards: [board('Acme', 'https://acme.example/jobs')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('searched');
    expect(results[0].postings).toHaveLength(2);
  });
});

describe('harvestPostings: blocked vs empty, reported distinctly', () => {
  it('reports blocked with blockKind "wall", never empty, when the page shows a CAPTCHA challenge', async () => {
    const call = stubBrowserCall(singleTabHandlers('Please complete the CAPTCHA to continue.'));

    const result = await harvestPostings({ boards: [board('Blocked Board', 'https://board.example/search')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('blocked');
    expect(results[0].blockKind).toBe('wall');
    expect(results[0].tier).toBe('');
    expect(results[0].postings).toEqual([]);
    expect(results[0].rawSnapshot).toBeUndefined();
  });

  it('does not misclassify an incidental reCAPTCHA footer notice as blocked when nothing else was extractable', async () => {
    const call = stubBrowserCall(
      singleTabHandlers('This site is protected by reCAPTCHA and the Google Privacy Policy and Terms of Service apply.'),
    );

    const result = await harvestPostings({ boards: [board('Odd Board', 'https://board.example/search')] }, call);

    const { results } = JSON.parse(result.content);
    // Ambiguous, not blocked: the tier-3 last resort, with the raw snapshot attached.
    expect(results[0].outcome).toBe('empty');
    expect(results[0].blockKind).toBeUndefined();
    expect(results[0].rawSnapshot).toContain('reCAPTCHA');
  });

  it('reports blocked with blockKind "unreachable", distinct from a bot wall, when navigation fails with a confirmed DNS error', async () => {
    const call = stubBrowserCall({
      browser_tab_new: { content: '[0]', isError: false },
      browser_tab_list: { content: '[0] about:blank', isError: false },
      browser_tab_select: { content: 'ok', isError: false },
      browser_navigate: { content: 'net::ERR_NAME_NOT_RESOLVED', isError: true },
      browser_tab_close: { content: 'ok', isError: false },
    });

    const result = await harvestPostings({ boards: [board('Down Board', 'https://dead-board.example/search')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('blocked');
    expect(results[0].blockKind).toBe('unreachable');
    expect(results[0].note).toContain('unreachable');
  });

  it('reports blocked with NO blockKind for a generic/timeout navigation failure, never mislabelling a slow board unreachable', async () => {
    const call = stubBrowserCall({
      browser_tab_new: { content: '[0]', isError: false },
      browser_tab_list: { content: '[0] about:blank', isError: false },
      browser_tab_select: { content: 'ok', isError: false },
      browser_navigate: { content: 'page.goto: Timeout 30000ms exceeded.', isError: true },
      browser_tab_close: { content: 'ok', isError: false },
    });

    const result = await harvestPostings({ boards: [board('Slow Board', 'https://slow-board.example/search')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('blocked');
    expect(results[0].blockKind).toBeUndefined();
    expect(results[0].note).not.toContain('unreachable');
  });

  it('reports empty when the board explicitly states no matches', async () => {
    const call = stubBrowserCall(singleTabHandlers('Sorry, no jobs found for your search.'));

    const result = await harvestPostings({ boards: [board('Quiet Board', 'https://board.example/search')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('empty');
    expect(results[0].tier).toBe('');
    expect(results[0].rawSnapshot).toBeUndefined();
  });

  it('does not treat "30 results" as an explicit zero-results empty, and still offers the tier-3 fallback', async () => {
    // The exact substring bug: "0 results" used to match inside "30 results",
    // producing a clean `empty` that also suppressed the raw-snapshot fallback
    // for a page that visibly has content whose links are not ATS-shaped.
    const call = stubBrowserCall(singleTabHandlers('Showing 30 results for "engineer".\n' + UNKNOWN_LINK));

    const result = await harvestPostings({ boards: [board('Busy Board', 'https://board.example/search')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('empty');
    expect(results[0].rawSnapshot).toContain('30 results');
  });

  it('reports empty with the raw snapshot attached (tier-3 last resort) when content exists but nothing matched', async () => {
    const call = stubBrowserCall(singleTabHandlers('A page full of content but no known ATS links.'));

    const result = await harvestPostings({ boards: [board('Odd Board', 'https://board.example/search')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('empty');
    expect(results[0].rawSnapshot).toContain('no known ATS links');
  });
});

describe('harvestPostings: a consent/bot-check phrase over real content is never data loss', () => {
  it('attaches the raw snapshot and reports empty (never blocked) for a consent banner sitting over 20 non-ATS job links', async () => {
    // An employer's own careers site — the common case for a direct board —
    // whose links are never ATS-shaped, with a cookie-consent banner on top.
    const links = Array.from(
      { length: 20 },
      (_, i) => `- link "Role ${i}" [ref=e${i}]: https://employer.example/careers/role-${i}`,
    ).join('\n');
    const snapshot = `We value your privacy - Accept all cookies\n${links}`;
    const call = stubBrowserCall(singleTabHandlers(snapshot));

    const result = await harvestPostings({ boards: [board('Employer Careers', 'https://employer.example/careers')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('empty');
    expect(results[0].blockKind).toBeUndefined();
    expect(results[0].postings).toEqual([]);
    expect(results[0].rawSnapshot).toBeDefined();
    expect(results[0].rawSnapshot).toContain('Role 0');
    expect(results[0].rawSnapshot).toContain('Role 19');
  });
});

describe('harvestPostings: structural wall detection beyond the literal phrase list', () => {
  const cases: { name: string; snapshot: string; blockKind: 'login' | 'wall' }[] = [
    { name: 'a sign-in gate phrased "Sign in to continue to Jobs"', snapshot: 'Sign in to continue to Jobs', blockKind: 'login' },
    { name: 'a sign-in gate phrased "Create an account or log in"', snapshot: 'Create an account or log in', blockKind: 'login' },
    { name: 'a GDPR consent modal with no other content', snapshot: 'We value your privacy - Accept all cookies', blockKind: 'wall' },
    { name: 'a Cloudflare bot-check interstitial', snapshot: 'Please wait while we check your browser before continuing...', blockKind: 'wall' },
  ];

  for (const { name, snapshot, blockKind } of cases) {
    it(`classifies ${name} as blocked (${blockKind}), never empty, with no raw snapshot`, async () => {
      const call = stubBrowserCall(singleTabHandlers(snapshot));

      const result = await harvestPostings({ boards: [board('Walled Board', 'https://board.example/search')] }, call);

      const { results } = JSON.parse(result.content);
      expect(results[0].outcome).toBe('blocked');
      expect(results[0].blockKind).toBe(blockKind);
      expect(results[0].rawSnapshot).toBeUndefined();
    });
  }
});

describe('harvestPostings: never navigates a sign-in/login URL', () => {
  it('refuses a board whose url is itself a sign-in page, without calling browser_navigate', async () => {
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const call = stubBrowserCall(singleTabHandlers(GREENHOUSE_LINK), calls);

    const result = await harvestPostings(
      { boards: [board('Login Board', 'https://board.example/users/sign-in?next=/jobs')] },
      call,
    );

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('blocked');
    expect(results[0].blockKind).toBe('login');
    expect(results[0].note).toContain('refused');
    expect(calls.some((c) => c.toolName === 'browser_navigate')).toBe(false);
  });

  it('refuses a Rails/Devise-style /users/sign_in (underscore) URL', async () => {
    const call = stubBrowserCall(singleTabHandlers(GREENHOUSE_LINK));

    const result = await harvestPostings({ boards: [board('Rails Board', 'https://board.example/users/sign_in')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('blocked');
    expect(results[0].blockKind).toBe('login');
  });

  it('refuses a URL whose query string names a login action (?action=login)', async () => {
    const call = stubBrowserCall(singleTabHandlers(GREENHOUSE_LINK));

    const result = await harvestPostings({ boards: [board('Query Login Board', 'https://board.example/account?action=login')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('blocked');
    expect(results[0].blockKind).toBe('login');
  });

  it('still harvests a board whose url merely mentions "login" outside a path segment boundary', async () => {
    // Guards the false-positive side: an ordinary board path must not be
    // refused just because it contains letters resembling a sign-in term.
    const call = stubBrowserCall(singleTabHandlers(GREENHOUSE_LINK));

    const result = await harvestPostings({ boards: [board('Acme', 'https://acme.example/jobs?ref=loginpage-promo')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('searched');
  });
});

describe('harvestPostings: search box typing', () => {
  it('types keywords into a detected search box and re-snapshots for postings', async () => {
    const firstSnapshot = '- searchbox "Search jobs" [ref=e5]';
    const secondSnapshot = GREENHOUSE_LINK;
    let snapshotCalls = 0;
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const call = stubBrowserCall(
      {
        browser_tab_new: { content: '[0]', isError: false },
        browser_tab_list: { content: '[0] https://acme.example/jobs', isError: false },
        browser_tab_select: { content: 'ok', isError: false },
        browser_navigate: { content: 'ok', isError: false },
        browser_snapshot: () => {
          snapshotCalls += 1;
          return { content: snapshotCalls === 1 ? firstSnapshot : secondSnapshot, isError: false };
        },
        browser_type: { content: 'ok', isError: false },
        browser_tab_close: { content: 'ok', isError: false },
      },
      calls,
    );

    const result = await harvestPostings(
      { boards: [{ board: 'Acme', url: 'https://acme.example/jobs', keywords: 'backend engineer' }] },
      call,
    );

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('searched');
    const typeCall = calls.find((c) => c.toolName === 'browser_type');
    expect(typeCall?.args).toMatchObject({ ref: 'e5', text: 'backend engineer', submit: true });
  });

  it('falls back to the original snapshot when no search box is found', async () => {
    const call = stubBrowserCall(singleTabHandlers(GREENHOUSE_LINK));

    const result = await harvestPostings(
      { boards: [{ board: 'Acme', url: 'https://acme.example/jobs', keywords: 'backend engineer' }] },
      call,
    );

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('searched');
  });

  it('classifies on the POST-search snapshot even when the search submit changes the first path segment', async () => {
    // https://careers.acme.com/jobs whose search submits to
    // https://careers.acme.com/search?q=... — a URL-prefix tab resolution
    // would lose this tab entirely; carrying the resolved tab INDEX through
    // the whole sequence must not.
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const preSearchSnapshot = ['- searchbox "Search jobs" [ref=e5]', UNKNOWN_LINK].join('\n');
    const inner = fakeTabBrowser(calls, (tab) => (tab.url.includes('/search') ? GREENHOUSE_LINK : preSearchSnapshot));
    // Override browser_type to simulate a client-side submit that navigates
    // the CURRENT tab to a different first path segment.
    const withSubmit: BrowserToolCall = async (toolName, args) => {
      if (toolName === 'browser_type') {
        calls.push({ toolName, args });
        await inner('browser_navigate', { url: 'https://careers.acme.com/search?q=backend' });
        return { content: 'ok', isError: false };
      }
      return inner(toolName, args);
    };

    const result = await harvestPostings(
      { boards: [{ board: 'Acme Careers', url: 'https://careers.acme.com/jobs', keywords: 'backend' }] },
      withSubmit,
    );

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('searched');
    expect(results[0].postings.some((p: { ats: string }) => p.ats === 'greenhouse')).toBe(true);
    // No leak: the created tab (index 1 — index 0 is the pre-seeded default) was closed.
    expect(calls.some((c) => c.toolName === 'browser_tab_close' && c.args.index === 1)).toBe(true);
  });
});

describe('harvestPostings: tab re-resolution never collides across a path boundary', () => {
  it('never misattributes postings between two boards sharing an origin and a path prefix (acme vs acme-eu)', async () => {
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const postingBySlug: Record<string, string> = {
      acme: '- link "EU-less role" [ref=e1]: https://boards.greenhouse.io/acme/jobs/1001',
      'acme-eu': '- link "EU role" [ref=e1]: https://boards.greenhouse.io/acme-eu/jobs/2002',
    };
    const call = fakeTabBrowser(calls, (tab) => {
      const slug = tab.url.split('/')[3] ?? '';
      return postingBySlug[slug] ?? 'no postings here';
    });
    const boards = [
      board('Acme', 'https://boards.greenhouse.io/acme/jobs'),
      board('Acme EU', 'https://boards.greenhouse.io/acme-eu/jobs'),
    ];

    const result = await harvestPostings({ boards }, call);

    const { results } = JSON.parse(result.content);
    const acme = results.find((r: { board: string }) => r.board === 'Acme');
    const acmeEu = results.find((r: { board: string }) => r.board === 'Acme EU');
    expect(acme.outcome).toBe('searched');
    expect(acmeEu.outcome).toBe('searched');
    expect(acme.postings.every((p: { url: string }) => p.url.includes('/acme/'))).toBe(true);
    expect(acmeEu.postings.every((p: { url: string }) => p.url.includes('/acme-eu/'))).toBe(true);
  });
});

describe('harvestPostings: no tab ever leaks', () => {
  it('closes the tab of a board whose browser_tab_new succeeded but browser_navigate failed (dead URL)', async () => {
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const call = stubBrowserCall(
      {
        browser_tab_list: { content: '[0] about:blank', isError: false },
        browser_tab_new: { content: '[0]', isError: false },
        browser_tab_select: { content: 'ok', isError: false },
        browser_navigate: { content: 'net::ERR_CONNECTION_REFUSED', isError: true },
        browser_tab_close: { content: 'ok', isError: false },
      },
      calls,
    );

    const result = await harvestPostings({ boards: [board('Dead Board', 'https://dead.example/jobs')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('blocked');
    expect(results[0].blockKind).toBe('unreachable');
    // The tab created for this board — even though it never navigated
    // successfully and stayed at about:blank — is still closed.
    expect(calls.filter((c) => c.toolName === 'browser_tab_close')).toHaveLength(1);
  });
});

describe('harvestPostings: several boards harvest concurrently over tabs', () => {
  it('harvests every board, opening one tab each and closing every tab only once all boards finished', async () => {
    const boards = ['One', 'Two', 'Three', 'Four', 'Five'].map((name, i) => board(name, `https://board${i}.example/jobs`));
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const call = fakeTabBrowser(calls, () => GREENHOUSE_LINK);

    const result = await harvestPostings({ boards }, call);

    const { results } = JSON.parse(result.content);
    expect(results).toHaveLength(5);
    expect(results.every((r: { outcome: string }) => r.outcome === 'searched')).toBe(true);
    expect(calls.filter((c) => c.toolName === 'browser_tab_new')).toHaveLength(5);
    // 5 created tabs closed; the pre-seeded default tab (index 0) is left untouched.
    expect(calls.filter((c) => c.toolName === 'browser_tab_close')).toHaveLength(5);
    expect(calls.some((c) => c.toolName === 'browser_tab_close' && c.args.index === 0)).toBe(false);
    // No tab closes until every board's own snapshot has already been taken.
    const lastSnapshot = calls.map((c) => c.toolName).lastIndexOf('browser_snapshot');
    const firstClose = calls.findIndex((c) => c.toolName === 'browser_tab_close');
    expect(firstClose).toBeGreaterThan(lastSnapshot);
  });

  it('reports a board unable to open a tab as blocked rather than crashing the rest', async () => {
    let tabNewCalls = 0;
    const call = stubBrowserCall({
      browser_tab_new: () => {
        tabNewCalls += 1;
        return tabNewCalls === 1 ? { content: 'no more tabs', isError: true } : { content: '[1]', isError: false };
      },
      browser_tab_list: { content: '[1] https://b.example', isError: false },
      browser_tab_select: { content: 'ok', isError: false },
      browser_navigate: { content: 'ok', isError: false },
      browser_snapshot: { content: GREENHOUSE_LINK, isError: false },
      browser_tab_close: { content: 'ok', isError: false },
    });

    const result = await harvestPostings({ boards: [board('A', 'https://a.example'), board('B', 'https://b.example')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results).toHaveLength(2);
    expect(results.some((r: { outcome: string; note: string }) => r.outcome === 'blocked' && r.note.includes('tab'))).toBe(
      true,
    );
  });

  it('closes every created tab correctly despite in-order-close renumbering, never misattributing a board\'s postings', async () => {
    // Simulates a real in-order-close renumbering browser: three boards each
    // get their own tab; browser_tab_close removes an entry and shifts every
    // later index down by one — exactly the hazard closeAllOpenedTabs's
    // descending-order close exists to defend against. All three share one
    // HOST (boards.greenhouse.io), distinguished only by path.
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const companies = ['alpha', 'beta', 'gamma'];
    const boards = companies.map((name, i) => board(`Board${i}`, `https://boards.greenhouse.io/${name}/jobs`));
    const postingByCompany: Record<string, string> = {
      alpha: '- link "Engineer at Alpha" [ref=e1]: https://boards.greenhouse.io/alpha/jobs/1001',
      beta: '- link "Engineer at Beta" [ref=e1]: https://boards.greenhouse.io/beta/jobs/2002',
      gamma: '- link "Engineer at Gamma" [ref=e1]: https://boards.greenhouse.io/gamma/jobs/3003',
    };
    let tabs: FakeTab[] = [{ index: 0, url: 'about:blank' }];
    let current: number | undefined;
    let nextRawIndex = 1;
    const call: BrowserToolCall = async (toolName, args) => {
      calls.push({ toolName, args });
      if (toolName === 'browser_tab_new') {
        const index = nextRawIndex++;
        tabs.push({ index, url: 'about:blank' });
        return { content: `[${index}]`, isError: false };
      }
      if (toolName === 'browser_tab_list') {
        return { content: tabs.map((t) => `[${t.index}] ${t.url}`).join('\n'), isError: false };
      }
      if (toolName === 'browser_tab_select') {
        const idx = args.index as number;
        if (!tabs.some((t) => t.index === idx)) return { content: 'no such tab', isError: true };
        current = idx;
        return { content: 'ok', isError: false };
      }
      if (toolName === 'browser_navigate') {
        const tab = tabs.find((t) => t.index === current);
        if (tab) tab.url = args.url as string;
        return { content: 'ok', isError: false };
      }
      if (toolName === 'browser_snapshot') {
        const tab = tabs.find((t) => t.index === current);
        const company = tab?.url.split('/')[3] ?? '';
        return { content: postingByCompany[company] ?? 'no postings here', isError: false };
      }
      if (toolName === 'browser_tab_close') {
        const idx = args.index as number;
        // A real in-order-close renumbering browser: remove, then renumber
        // every SURVIVING tab sequentially from 0 — closing descending
        // (highest first) is what keeps every not-yet-closed tracked index
        // valid despite this.
        tabs = tabs.filter((t) => t.index !== idx).map((t, i) => ({ ...t, index: i }));
        return { content: 'ok', isError: false };
      }
      return { content: 'ok', isError: false };
    };

    const result = await harvestPostings({ boards }, call);

    const { results } = JSON.parse(result.content);
    expect(results).toHaveLength(3);
    for (let i = 0; i < results.length; i += 1) {
      expect(results[i].outcome).toBe('searched');
      for (const posting of results[i].postings) {
        expect(posting.url).toContain(`/${companies[i]}/`);
      }
    }
    // Every created tab was actually closed; only the pre-existing default
    // tab (renumbered to index 0) survives.
    expect(tabs).toHaveLength(1);
    expect(tabs[0].url).toBe('about:blank');
  });
});

describe('harvestPostings: the tab-listing text format is probed at runtime, never assumed', () => {
  it('parses the pinned @playwright/mcp@0.0.79 tab-listing format ("- N: (current) [Title] (https://…)")', async () => {
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const render079 = (t: FakeTab) => `- ${t.index}: ${t.index === 0 ? '(current) ' : ''}[Board ${t.index}] (${t.url})`;
    const call = fakeTabBrowser(calls, () => GREENHOUSE_LINK, render079);
    const boards = [board('One', 'https://board1.example/jobs'), board('Two', 'https://board2.example/jobs')];
    const stderrLines: string[] = [];
    vi.spyOn(process.stderr, 'write').mockImplementation((chunk: unknown) => {
      stderrLines.push(String(chunk));
      return true;
    });

    const result = await harvestPostings({ boards }, call);

    const { results } = JSON.parse(result.content);
    expect(results.every((r: { outcome: string }) => r.outcome === 'searched')).toBe(true);
    expect(calls.filter((c) => c.toolName === 'browser_tab_new')).toHaveLength(2);
    expect(calls.filter((c) => c.toolName === 'browser_tab_close')).toHaveLength(2);
    expect(stderrLines.some((line) => line.includes('"mode":"concurrent-tabs"'))).toBe(true);
  });

  it('degrades to serial, still harvesting every board, when the tab listing is entirely unrecognised', async () => {
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const call = stubBrowserCall(
      {
        browser_tab_list: { content: 'Currently open pages:\nHome page, no index shown here.', isError: false },
        browser_navigate: { content: 'ok', isError: false },
        browser_snapshot: { content: GREENHOUSE_LINK, isError: false },
      },
      calls,
    );
    const boards = ['One', 'Two', 'Three'].map((name, i) => board(name, `https://board${i}.example/jobs`));
    const stderrLines: string[] = [];
    vi.spyOn(process.stderr, 'write').mockImplementation((chunk: unknown) => {
      stderrLines.push(String(chunk));
      return true;
    });

    const result = await harvestPostings({ boards }, call);

    expect(result.isError).toBe(false);
    const { results, degradedReason } = JSON.parse(result.content);
    expect(results).toHaveLength(3);
    expect(results.every((r: { outcome: string; tier: string }) => r.outcome === 'searched' && r.tier === 'harvest')).toBe(
      true,
    );
    expect(typeof degradedReason).toBe('string');
    expect(degradedReason.length).toBeGreaterThan(0);
    // Only the probe's own browser_tab_list call is made; no other tab tool at all.
    expect(calls.filter((c) => c.toolName === 'browser_tab_list')).toHaveLength(1);
    expect(calls.some((c) => c.toolName.startsWith('browser_tab_') && c.toolName !== 'browser_tab_list')).toBe(false);
    expect(stderrLines.some((line) => line.includes('"mode":"serial"') && line.includes('tab-list-unparseable'))).toBe(
      true,
    );
  });
});

describe('harvestPostings: degraded serial mode when tab tools are unavailable', () => {
  it('harvests every board serially in the single shared tab, calling no tab tool, with the same result shape', async () => {
    const boards = ['One', 'Two', 'Three'].map((name, i) => board(name, `https://board${i}.example/jobs`));
    const calls: { toolName: string; args: Record<string, unknown> }[] = [];
    const stderrLines: string[] = [];
    const stderrSpy = vi.spyOn(process.stderr, 'write').mockImplementation((chunk: unknown) => {
      stderrLines.push(String(chunk));
      return true;
    });
    const call = stubBrowserCall(
      {
        browser_navigate: { content: 'ok', isError: false },
        browser_snapshot: { content: GREENHOUSE_LINK, isError: false },
      },
      calls,
    );

    const result = await harvestPostings({ boards }, call, false);
    stderrSpy.mockRestore();

    expect(result.isError).toBe(false);
    const { results } = JSON.parse(result.content);
    expect(results).toHaveLength(3);
    expect(results.every((r: { outcome: string; tier: string }) => r.outcome === 'searched' && r.tier === 'harvest')).toBe(
      true,
    );
    // No tab tool is ever called in the degraded path.
    expect(calls.some((c) => c.toolName.startsWith('browser_tab_'))).toBe(false);
    expect(calls.filter((c) => c.toolName === 'browser_navigate')).toHaveLength(3);
    // The mode is logged, without any page content in the line.
    expect(stderrLines.some((line) => line.includes('"mode":"serial"'))).toBe(true);
    expect(stderrLines.every((line) => !line.includes(GREENHOUSE_LINK))).toBe(true);
  });

  it('confines one board\'s thrown transport error to that board, without discarding the others', async () => {
    const boards = ['One', 'Two', 'Three'].map((name, i) => board(name, `https://board${i}.example/jobs`));
    const call: BrowserToolCall = async (toolName, args) => {
      if (toolName === 'browser_navigate' && (args.url as string).includes('board1')) {
        throw new Error('mcp connection lost');
      }
      if (toolName === 'browser_navigate') return { content: 'ok', isError: false };
      return { content: GREENHOUSE_LINK, isError: false };
    };

    const result = await harvestPostings({ boards }, call, false);

    expect(result.isError).toBe(false);
    const { results } = JSON.parse(result.content);
    expect(results).toHaveLength(3);
    expect(results[0].outcome).toBe('searched');
    expect(results[1].outcome).toBe('blocked');
    expect(results[1].note).toContain('mcp connection lost');
    // A thrown, confined failure carries no blockKind — it is an internal
    // tool failure, not a signal read from the page.
    expect(results[1].blockKind).toBeUndefined();
    expect(results[2].outcome).toBe('searched');
  });
});

describe('harvestPostings: concurrent per-board failure containment', () => {
  it('confines one board\'s thrown error to that board even in the concurrent tab-per-board path', async () => {
    const boards = [board('Good', 'https://good.example/jobs'), board('Bad', 'https://bad.example/jobs')];
    const call: BrowserToolCall = async (toolName, args) => {
      if (toolName === 'browser_navigate' && JSON.stringify(args).includes('bad.example')) {
        throw new Error('transport exploded');
      }
      if (toolName === 'browser_tab_new') return { content: '[0]', isError: false };
      if (toolName === 'browser_tab_list') return { content: '[0] about:blank', isError: false };
      if (toolName === 'browser_tab_select') return { content: 'ok', isError: false };
      if (toolName === 'browser_navigate') return { content: 'ok', isError: false };
      if (toolName === 'browser_snapshot') return { content: GREENHOUSE_LINK, isError: false };
      return { content: 'ok', isError: false };
    };

    const result = await harvestPostings({ boards }, call);

    expect(result.isError).toBe(false);
    const { results } = JSON.parse(result.content);
    expect(results).toHaveLength(2);
    const good = results.find((r: { board: string }) => r.board === 'Good');
    const bad = results.find((r: { board: string }) => r.board === 'Bad');
    expect(good.outcome).toBe('searched');
    expect(bad.outcome).toBe('blocked');
    expect(bad.note).toContain('transport exploded');
  });
});

describe('harvestPostings: argument validation and error handling', () => {
  it('returns isError when boards is missing or empty', async () => {
    const call = vi.fn();
    const result = await harvestPostings({}, call as unknown as BrowserToolCall);
    expect(result.isError).toBe(true);
    expect(result.content).toContain('boards');
    expect(call).not.toHaveBeenCalled();
  });

  it('drops malformed board entries and keeps valid ones', async () => {
    const call = stubBrowserCall(singleTabHandlers(GREENHOUSE_LINK));

    const result = await harvestPostings({ boards: [{ board: '' }, board('Valid', 'https://valid.example')] }, call);

    const { results } = JSON.parse(result.content);
    expect(results).toHaveLength(1);
    expect(results[0].board).toBe('Valid');
  });

  it('drops a location argument rather than acting on it', async () => {
    const call = stubBrowserCall(singleTabHandlers(GREENHOUSE_LINK));

    const result = await harvestPostings(
      { boards: [{ board: 'Acme', url: 'https://acme.example/jobs', location: 'Berlin' }] },
      call,
    );

    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('searched');
  });

  it('never throws when the top-level browser call throws before any board starts, returning isError instead', async () => {
    const call: BrowserToolCall = async () => {
      throw new Error('mcp connection lost');
    };

    const result = await harvestPostings({ boards: [board('Acme', 'https://acme.example')] }, call, false);

    // The degraded serial path still confines the failure per-board rather
    // than surfacing it as a whole-call isError, since harvestOneBoardSafely
    // catches it — this call is never itself an isError result.
    expect(result.isError).toBe(false);
    const { results } = JSON.parse(result.content);
    expect(results[0].outcome).toBe('blocked');
    expect(results[0].note).toContain('mcp connection lost');
  });
});
