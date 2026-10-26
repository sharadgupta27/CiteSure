/**
 * Locating a cited quote inside the text layer of a PDF page, and turning a text selection into normalised rectangles.
 *
 * PDF text comes in arbitrary items (usually one per line or font run) and differs from the parsed text the quote was
 * taken from: ligatures (ﬁ), soft or line-end hyphens, line breaks, curly quotes. So matching is done on a "squashed"
 * form, lower-case letters and digits only, with a map from every squashed character back to its item and offset.
 */

export interface ItemSpan {
  /** Index into the items array. */
  item: number;
  /** UTF-16 offsets inside that item's string. */
  start: number;
  end: number;
}

export interface QuoteMatch {
  /** False when only the beginning (or the beginning and end) of the quote could be found. */
  exact: boolean;
  spans: ItemSpan[];
}

interface Squashed {
  text: string;
  /** For every character of `text`: the item and the UTF-16 range it came from. */
  origin: { item: number; start: number; end: number }[];
}

const KEEP = /[\p{L}\p{N}]/u;

function squash(items: readonly string[]): Squashed {
  let text = "";
  const origin: Squashed["origin"] = [];
  items.forEach((value, item) => {
    let index = 0;
    for (const char of value) {
      const start = index;
      index += char.length;
      // NFKC expands ligatures (ﬁ -> fi) and folds full-width forms; a char can become several letters.
      for (const letter of char.normalize("NFKC").toLowerCase()) {
        if (!KEEP.test(letter)) continue;
        text += letter;
        // `letter` may be several UTF-16 units; the map is per UTF-16 unit of `text` so indexOf offsets line up.
        for (let i = 0; i < letter.length; i++) origin.push({ item, start, end: index });
      }
    }
  });
  return { text, origin };
}

/** The quote in the same squashed form, for comparison and for tests. */
export function squashText(value: string): string {
  return squash([value]).text;
}

function spansFor(page: Squashed, from: number, to: number): ItemSpan[] {
  const spans: ItemSpan[] = [];
  for (let i = from; i < to; i++) {
    const o = page.origin[i];
    if (!o) continue;
    const last = spans[spans.length - 1];
    if (last && last.item === o.item) last.end = Math.max(last.end, o.end);
    else spans.push({ item: o.item, start: o.start, end: o.end });
  }
  return spans;
}

const EDGE = 40;
const MIN_QUOTE = 8;

/** Find `quote` in the page's text items. Returns null when it is not there (or the quote is too short to trust). */
export function locateQuote(items: readonly string[], quote: string): QuoteMatch | null {
  const target = squashText(quote);
  if (target.length < MIN_QUOTE) return null;
  const page = squash(items);
  const at = page.text.indexOf(target);
  if (at >= 0) return { exact: true, spans: spansFor(page, at, at + target.length) };
  if (target.length < EDGE * 2) return null;
  // The parsed text and the page text can differ in the middle (a footnote mark, an OCR slip). Anchor on both ends.
  const head = page.text.indexOf(target.slice(0, EDGE));
  if (head < 0) return null;
  const tailAt = page.text.indexOf(target.slice(-EDGE), head);
  if (tailAt >= 0 && tailAt + EDGE - head <= target.length * 1.5) {
    return { exact: false, spans: spansFor(page, head, tailAt + EDGE) };
  }
  return { exact: false, spans: spansFor(page, head, head + EDGE) };
}

export interface NormalizedRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface BoxLike {
  left: number;
  top: number;
  width: number;
  height: number;
}

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

/** Client rectangles (as from Range.getClientRects) to fractions of the page box, dropping slivers and duplicates. */
export function normalizeRects(rects: readonly BoxLike[], box: BoxLike, max = 100): NormalizedRect[] {
  if (box.width <= 0 || box.height <= 0) return [];
  const out: NormalizedRect[] = [];
  const seen = new Set<string>();
  for (const r of rects) {
    if (r.width < 1 || r.height < 1) continue;
    const x = clamp01((r.left - box.left) / box.width);
    const y = clamp01((r.top - box.top) / box.height);
    const w = clamp01(r.width / box.width);
    const h = clamp01(r.height / box.height);
    if (w <= 0 || h <= 0) continue;
    const rect = { x, y, w: Math.min(w, 1 - x), h: Math.min(h, 1 - y) };
    const key = [rect.x, rect.y, rect.w, rect.h].map((n) => n.toFixed(4)).join(",");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(rect);
    if (out.length >= max) break;
  }
  return out;
}
