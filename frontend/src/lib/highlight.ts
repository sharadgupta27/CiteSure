/**
 * Mapping a citation's quote span onto text so the viewer can highlight it.
 *
 * Gotcha: the backend (Python) counts characters as Unicode code points; JavaScript strings count UTF-16 code units.
 * They differ for characters outside the Basic Multilingual Plane (emoji, some CJK), so offsets must be converted
 * or the highlight drifts by one character per emoji.
 */

export interface Range {
  start: number;
  end: number;
}

export interface Segment {
  text: string;
  highlighted: boolean;
}

/** Convert a code point index (Python) to a UTF-16 index (JavaScript). Out-of-range values are clamped. */
export function codePointToUtf16(text: string, codePointIndex: number): number {
  if (codePointIndex <= 0) return 0;
  let utf16 = 0;
  let seen = 0;
  while (utf16 < text.length && seen < codePointIndex) {
    const code = text.codePointAt(utf16) ?? 0;
    utf16 += code > 0xffff ? 2 : 1;
    seen += 1;
  }
  return utf16;
}

/** Sort, clamp and merge overlapping ranges. Empty and inverted ranges are dropped. */
export function normaliseRanges(ranges: Range[], length: number): Range[] {
  const valid = ranges
    .map((r) => ({ start: Math.max(0, Math.min(r.start, length)), end: Math.max(0, Math.min(r.end, length)) }))
    .filter((r) => r.end > r.start)
    .sort((a, b) => a.start - b.start);
  const merged: Range[] = [];
  for (const range of valid) {
    const last = merged[merged.length - 1];
    if (last && range.start <= last.end) last.end = Math.max(last.end, range.end);
    else merged.push({ ...range });
  }
  return merged;
}

/** Split text into alternating plain / highlighted segments. `ranges` are in code points, as sent by the API. */
export function segmentText(text: string, ranges: Range[]): Segment[] {
  const utf16Ranges = ranges.map((r) => ({
    start: codePointToUtf16(text, r.start),
    end: codePointToUtf16(text, r.end),
  }));
  const merged = normaliseRanges(utf16Ranges, text.length);
  if (merged.length === 0) return [{ text, highlighted: false }];
  const segments: Segment[] = [];
  let cursor = 0;
  for (const range of merged) {
    if (range.start > cursor) segments.push({ text: text.slice(cursor, range.start), highlighted: false });
    segments.push({ text: text.slice(range.start, range.end), highlighted: true });
    cursor = range.end;
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), highlighted: false });
  return segments;
}
