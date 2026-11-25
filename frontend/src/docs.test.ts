// The written guides are checked like code: a broken screenshot reference or a drifting timeline fails the build.
import { describe, it, expect } from 'vitest';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const docs = join(here, '..', '..', 'docs');
const read = (...parts: string[]) => readFileSync(join(docs, ...parts), 'utf-8').replace(/\r\n/g, '\n');
const seconds = (t: string) => { const [m, s] = t.split(':').map(Number); return m * 60 + s; };

const storyboards = readdirSync(join(docs, 'video-guide')).filter((f) => /^0[1-9]-.*\.md$/.test(f)).sort();

describe('user guide', () => {
  const guide = read('user-guide', 'README.md');

  it('only points at screenshots that exist, and uses every screenshot', () => {
    const referenced = [...guide.matchAll(/!\[[^\]]*\]\((images\/[^)]+)\)/g)].map((m) => m[1]);
    expect(referenced.length).toBeGreaterThan(20);
    for (const ref of referenced) expect(existsSync(join(docs, 'user-guide', ref)), ref).toBe(true);
    const onDisk = readdirSync(join(docs, 'user-guide', 'images')).map((f) => `images/${f}`);
    expect(onDisk.filter((f) => !referenced.includes(f)), 'screenshots no guide section uses').toEqual([]);
  });

  it('has a contents link for every section it lists', () => {
    const slug = (t: string) => t.toLowerCase().replace(/[^a-z0-9\s-]/g, '').trim().replace(/\s+/g, '-');
    const headings = new Set([...guide.matchAll(/^#{2,3} (.+)$/gm)].map((m) => slug(m[1])));
    for (const m of guide.matchAll(/\]\(#([^)]+)\)/g)) expect(headings.has(m[1]), m[1]).toBe(true);
  });
});

describe('video storyboards', () => {
  it('exist for the four planned videos', () => {
    expect(storyboards).toHaveLength(4);
  });

  for (const file of storyboards) {
    describe(file, () => {
      const text = read('video-guide', file);
      const scenes = [...text.matchAll(/^### Scene (\d+) — (.+) \((\d+:\d+) – (\d+:\d+)\)$/gm)];

      it('points at screenshots that exist', () => {
        const refs = [...text.matchAll(/!\[[^\]]*\]\((\.\.\/user-guide\/images\/[^)]+)\)/g)].map((m) => m[1]);
        expect(refs.length).toBeGreaterThanOrEqual(scenes.length);
        for (const ref of refs) expect(existsSync(join(docs, 'video-guide', ref)), ref).toBe(true);
        for (const m of text.matchAll(/`(\d\d-[a-z-]+\.png)`/g)) expect(existsSync(join(docs, 'user-guide', 'images', m[1])), m[1]).toBe(true);
      });

      it('gives every scene narration, on-screen notes and a picture', () => {
        const parts = text.split(/^### Scene /m).slice(1);
        expect(parts.length).toBe(scenes.length);
        for (const p of parts) {
          expect(p).toMatch(/\*\*Narration:\*\* .{40,}/);
          expect(p).toMatch(/\*\*On screen:\*\* .{10,}/);
          expect(p).toMatch(/!\[[^\]]*\]\(/);
        }
      });

      it('has a timeline with no gaps or overlaps, numbered in order', () => {
        scenes.forEach((s, i) => {
          expect(Number(s[1])).toBe(i + 1);
          expect(seconds(s[4])).toBeGreaterThan(seconds(s[3]));
          expect(seconds(s[3])).toBe(i === 0 ? 0 : seconds(scenes[i - 1][4]));
        });
      });

      it('has chapter markers that match the scene start times, and a one-line summary', () => {
        const markers = /\*\*Chapter markers:\*\* (.+)/.exec(text)?.[1].split(' · ').map((c) => c.trim()) ?? [];
        expect(markers.map((c) => c.split(' ')[0])).toEqual(scenes.map((s) => s[3]));
        expect(text).toMatch(/\*\*One-line summary:\*\* .{20,}/);
      });

      it('has narration that fits the timeline (at most about 190 words a minute, so it can be read calmly)', () => {
        const words = [...text.matchAll(/\*\*Narration:\*\* (.+)/g)].reduce((n, m) => n + m[1].split(/\s+/).length, 0);
        const minutes = seconds(scenes[scenes.length - 1][4]) / 60;
        expect(words / minutes).toBeLessThan(190);
        expect(words / minutes).toBeGreaterThan(70);                          // and not so thin that the video is mostly silence
      });
    });
  }
});
