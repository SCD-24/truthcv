import { describe, expect, it } from 'vitest';
import { pruneSnapshot } from '../snapshotPrune.js';

const NAV_ITEMS = ['Home', 'My Network', 'Jobs', 'Messaging', 'Notifications', 'Me', 'For Business'];
const navLines = NAV_ITEMS.map((n) => `      - listitem [ref=e${n.length}]:\n        - link "${n}" [ref=e9] [cursor=pointer]:\n          - /url: https://www.linkedin.com/x`);
const FOOTER_LINKS = ['About', 'Accessibility', 'Help Center', 'Privacy & Terms', 'Ad Choices'];
const footerLines = FOOTER_LINKS.map((n) => `    - link "${n}" [ref=e20]:\n      - /url: https://www.linkedin.com/legal`);

const FIXTURE = [
  '### Page',
  '- Page URL: https://www.linkedin.com/jobs/view/123',
  '- Page Title: Data Architect | Archer | LinkedIn',
  '- Console: 1 errors',
  '### Snapshot',
  '```yaml',
  '- generic [ref=e1]:',
  '  - banner [ref=e2]:',
  '    - navigation "Primary" [ref=e3]:',
  '      - list [ref=e4]:',
  ...navLines,
  '  - main [ref=e30]:',
  '    - region "Primary content" [ref=e31]:',
  '      - heading "Senior Data Architect" [level=1] [ref=e32]',
  '      - paragraph [ref=e33]: Design enterprise data platforms.',
  '      - list [ref=e34]:',
  '        - listitem [ref=e35]: Five years of SQL',
  '        - listitem [ref=e36]: Cloud experience',
  '  - complementary "Aside" [ref=e40]:',
  '    - heading "Try Premium for free" [level=2] [ref=e41]',
  '    - button "Try Premium" [ref=e42]',
  '  - generic "Footer" [ref=e50]:',
  ...footerLines,
  '    - combobox "Select language" [ref=e60]:',
  '      - option "Deutsch (German)" [ref=e61]',
  '```',
].join('\n');

describe('pruneSnapshot attribute tokens', () => {
  it('drops an expanded combobox with its options', () => {
    const out = pruneSnapshot('- combobox "X" [ref=e1] [expanded]:\n  - option "Opt A" [ref=e4]\n- paragraph: kept');
    expect(out).toBe('kept');
  });
  it('flattens a button with extra attributes', () => {
    expect(pruneSnapshot('- button "Apply now" [ref=e2] [expanded]')).toBe('Apply now');
  });
  it('keeps bracketed text inside quoted names', () => {
    expect(pruneSnapshot('- heading "Engineer [Remote]" [level=2] [ref=e3]')).toBe('## Engineer [Remote]');
  });
});

describe('pruneSnapshot', () => {
  const out = pruneSnapshot(FIXTURE);
  it('drops chrome text', () => {
    for (const s of ['My Network', 'Accessibility', 'Deutsch (German)', 'Premium', 'Select language']) {
      expect(out).not.toContain(s);
    }
  });
  it('keeps title and posting text', () => {
    expect(out.split('\n')[0]).toBe('Title: Data Architect | Archer | LinkedIn');
    expect(out).toContain('# Senior Data Architect');
    expect(out).toContain('Design enterprise data platforms.');
    expect(out).toContain('- Five years of SQL');
  });
  it('strips urls, refs and headers', () => {
    expect(out).not.toContain('/url:');
    expect(out).not.toContain('[ref=');
    expect(out).not.toContain('### Page');
    expect(out).not.toContain('```');
  });
  it('is much shorter than chrome-heavy input', () => {
    expect(out.length).toBeLessThan(FIXTURE.length * 0.3);
  });
  it('is deterministic and collapses duplicates', () => {
    expect(pruneSnapshot(FIXTURE)).toBe(out);
    expect(pruneSnapshot('- paragraph: a\n- paragraph: a')).toBe('a');
  });
});
