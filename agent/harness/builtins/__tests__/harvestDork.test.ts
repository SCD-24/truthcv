import { describe, expect, it } from 'vitest';
import { extractDorkPostings, parseDorkTarget, unwrapGoogleRedirect } from '../harvestDork.js';
import type { ResolvedLink } from '../harvestLinks.js';

const link = (title: string, url: string): ResolvedLink => ({ title, url: new URL(url) });

describe('parseDorkTarget', () => {
  it('parses site:jobs.lever.co', () => {
    expect(parseDorkTarget('https://www.google.com/search?q=site%3Ajobs.lever.co+engineer')).toEqual({ host: 'jobs.lever.co', pathPrefix: '' });
  });
  it('parses a path prefix', () => {
    expect(parseDorkTarget('https://www.google.de/search?q=site:LinkedIn.com/jobs+x')).toEqual({ host: 'linkedin.com', pathPrefix: '/jobs' });
  });
  it('returns null for non-Google pages', () => {
    expect(parseDorkTarget('https://example.com/search?q=site:jobs.lever.co')).toBeNull();
  });
});

describe('extractDorkPostings', () => {
  it('enforces path prefix', () => {
    const target = { host: 'linkedin.com', pathPrefix: '/jobs' };
    const out = extractDorkPostings([link('A job', 'https://linkedin.com/jobs/view/1'), link('Other', 'https://linkedin.com/in/bob')], target);
    expect(out.map((p) => p.url)).toEqual(['https://linkedin.com/jobs/view/1']);
    expect(out[0].ats).toBe('dork-site');
  });
  it('requires a path segment boundary', () => {
    const target = { host: 'linkedin.com', pathPrefix: '/jobs' };
    const out = extractDorkPostings([link('Arch', 'https://linkedin.com/jobs-archive/345'), link('Job', 'https://linkedin.com/jobs/view/123')], target);
    expect(out.map((p) => p.url)).toEqual(['https://linkedin.com/jobs/view/123']);
  });
  it('accepts LinkedIn slugged job URLs and rejects non-job paths', () => {
    const target = { host: 'linkedin.com', pathPrefix: '/jobs' };
    const good = 'https://ie.linkedin.com/jobs/view/senior-data-architect-at-archer-4473914860';
    const bad = ['https://ie.linkedin.com/jobs/%E7%B3%96%E6%9E%9C-jobs', 'https://www.linkedin.com/jobs/search?keywords=x', 'https://linkedin.com/jobs/view/abc'];
    const out = extractDorkPostings([good, ...bad].map((u) => link('t', u)), target);
    expect(out.map((p) => p.url)).toEqual([good]);
  });
  it('matches subdomains', () => {
    const out = extractDorkPostings([link('Role', 'https://acme.wd3.myworkdayjobs.com/en/job/1')], { host: 'myworkdayjobs.com', pathPrefix: '' });
    expect(out).toHaveLength(1);
  });
  it('unwraps /url?q= redirects', () => {
    const wrapped = new URL('https://www.google.com/url?q=https://jobs.lever.co/acme/123&sa=U');
    expect(unwrapGoogleRedirect(wrapped).href).toBe('https://jobs.lever.co/acme/123');
    const out = extractDorkPostings([link('Role', wrapped.href)], { host: 'jobs.lever.co', pathPrefix: '' });
    expect(out[0].url).toBe('https://jobs.lever.co/acme/123');
  });
  it('ignores Google-internal links and bare root', () => {
    const out = extractDorkPostings([link('Images', 'https://www.google.com/imghp'), link('Home', 'https://jobs.lever.co/')], { host: 'jobs.lever.co', pathPrefix: '' });
    expect(out).toEqual([]);
  });
});
