/**
 * A stand-in for `pdfjs-dist` in jsdom tests (the real library needs a browser canvas and a worker).
 * Use: vi.mock("pdfjs-dist", async () => (await import("../test/fakePdfjs")).fakePdfjs)
 * and vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "/worker.js" })).
 */
import { vi } from "vitest";

/** Text items per page (index 0 is page 1). Tests may replace the contents. */
export const fakePages: string[][] = [
  ["Welcome to the parental leave policy."],
  ["Primary caregivers receive ", "16 weeks of fully paid leave.", " Secondary caregivers receive 8 weeks."],
  ["Requests are made through the HR portal."],
];

export const getDocumentSpy = vi.fn();

const page = (number: number) => ({
  getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale, scale }),
  render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }),
  streamTextContent: () => ({ page: number }),
  getTextContent: async () => ({ items: (fakePages[number - 1] ?? []).map((str) => ({ str })) }),
});

class FakeTextLayer {
  textDivs: HTMLElement[] = [];
  private readonly container: HTMLElement;
  private readonly source: { page: number };
  constructor(options: { container: HTMLElement; textContentSource: { page: number } }) {
    this.container = options.container;
    this.source = options.textContentSource;
  }
  async render() {
    for (const str of fakePages[this.source.page - 1] ?? []) {
      const span = document.createElement("span");
      span.textContent = str;
      this.container.append(span);
      this.textDivs.push(span);
    }
  }
}

export const fakePdfjs = {
  GlobalWorkerOptions: {} as { workerSrc?: string },
  TextLayer: FakeTextLayer,
  getDocument: (options: unknown) => {
    getDocumentSpy(options);
    const doc = {
      get numPages() {
        return fakePages.length;
      },
      getPage: async (n: number) => page(n),
      destroy: vi.fn(async () => undefined),
    };
    return { promise: Promise.resolve(doc), destroy: vi.fn(async () => undefined) };
  },
};
