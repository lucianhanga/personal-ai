import "@testing-library/jest-dom/vitest";

// jsdom gaps used by the app under test.
if (typeof globalThis.localStorage === "undefined") {
  const store = new Map<string, string>();
  globalThis.localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size;
    },
  } as Storage;
}

if (typeof Element !== "undefined" && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}

// jsdom doesn't decode images: fire `onload` on src-set with 0 dimensions so the image-downscale
// helper (#419) resolves (0 dims -> "no downscale needed" -> returns the original data-URL).
class FakeImage {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  naturalWidth = 0;
  naturalHeight = 0;
  set src(_v: string) {
    queueMicrotask(() => this.onload?.());
  }
}
globalThis.Image = FakeImage as unknown as typeof Image;
