import * as matchers from '@testing-library/jest-dom/matchers';
import { expect } from 'vitest';

expect.extend(matchers);

// React Flow requires ResizeObserver which jsdom doesn't provide
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Newer Node versions define a `localStorage` global that is unusable without a file, and it shadows jsdom's.
// Give every test a plain in-memory Storage so code that remembers things in the browser can be tested.
function memoryStorage(): Storage {
  let data = new Map<string, string>();
  return {
    get length() { return data.size; },
    clear: () => { data = new Map(); },
    getItem: (key: string) => (data.has(key) ? data.get(key)! : null),
    key: (index: number) => Array.from(data.keys())[index] ?? null,
    removeItem: (key: string) => { data.delete(key); },
    setItem: (key: string, value: string) => { data.set(key, String(value)); },
  };
}
for (const name of ['localStorage', 'sessionStorage'] as const) {
  Object.defineProperty(globalThis, name, { value: memoryStorage(), configurable: true, writable: true });
}
