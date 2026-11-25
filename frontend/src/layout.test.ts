// jsdom does no layout, so a page that cannot scroll passes every component test. This guards the cause instead:
// the page itself never scrolls (the editor fills the window), so each full-page screen must scroll inside its own container.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'index.css'), 'utf-8').replace(/\r\n/g, '\n');

/** The declarations of the rule whose selector is exactly `selector` (at the start of a line). */
const rule = (selector: string): string => {
  const escaped = selector.replace(/[.>]/g, (c) => `\\${c}`);
  const m = new RegExp(String.raw`(?:^|\n)${escaped}\s*\{([^}]*)\}`).exec(css);
  if (!m) throw new Error(`no CSS rule for ${selector}`);
  return m[1];
};

describe('page scrolling', () => {
  it('the document itself does not scroll (which is why pages must)', () => {
    expect(rule('body')).toMatch(/overflow:\s*hidden/);
  });

  for (const selector of ['.landing', '.guide-page', '.auth-page']) {
    it(`${selector} scrolls inside its own container`, () => {
      const body = rule(selector);
      expect(body).toMatch(/height:\s*100vh/);
      expect(body).toMatch(/overflow-y:\s*auto/);
    });
  }

  it('a card centred in a scrolling page keeps its top reachable (margin: auto, not align-items: center)', () => {
    expect(rule('.auth-page > .auth-card')).toMatch(/margin:\s*auto/);
    expect(rule('.auth-page')).not.toMatch(/align-items:\s*center/);
  });

  it('the guard can fail: a rule without the scrolling declarations is caught', () => {
    // sanity check of the helper itself, using a rule that exists but does not scroll
    expect(rule('.app')).not.toMatch(/overflow-y:\s*auto/);
  });
});
