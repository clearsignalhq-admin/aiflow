import { describe, it, expect } from 'vitest';
import { formatApiError } from './apiError';

describe('formatApiError', () => {
  it('returns string detail as-is', () => {
    expect(formatApiError({ detail: 'Request body too large (max 1000 KB).' }, 413))
      .toBe('Request body too large (max 1000 KB).');
  });

  it('formats FastAPI validation arrays', () => {
    const msg = formatApiError(
      { detail: [{ loc: ['body', 'workflow', 'nodes'], msg: 'List should have at most 100 items' }] },
      422,
    );
    expect(msg).toBe('workflow → nodes: List should have at most 100 items');
  });

  it('notes additional validation errors', () => {
    const msg = formatApiError({ detail: [{ loc: ['body', 'a'], msg: 'x' }, { loc: ['body', 'b'], msg: 'y' }] }, 422);
    expect(msg).toContain('(+1 more)');
  });

  it('falls back by status when there is no detail', () => {
    expect(formatApiError({}, 413)).toMatch(/too large/i);
    expect(formatApiError(null, 422)).toMatch(/not valid/i);
    expect(formatApiError(undefined, 500)).toBe('Server error (500)');
  });
});
