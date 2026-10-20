import { codePointToUtf16, normaliseRanges, segmentText } from "./highlight";

describe("codePointToUtf16", () => {
  it("is the identity for plain ASCII", () => {
    expect(codePointToUtf16("hello world", 6)).toBe(6);
  });

  it("counts an emoji as one code point but two UTF-16 units", () => {
    const text = "Hi 😀 there"; // the emoji is 2 UTF-16 units; Python counts it as 1 character
    expect(codePointToUtf16(text, 3)).toBe(3);
    expect(codePointToUtf16(text, 4)).toBe(5); // right after the emoji
    expect(codePointToUtf16(text, 5)).toBe(6);
  });

  it("clamps out-of-range indexes", () => {
    expect(codePointToUtf16("abc", -5)).toBe(0);
    expect(codePointToUtf16("abc", 99)).toBe(3);
  });
});

describe("normaliseRanges", () => {
  it("sorts, merges overlaps and drops empty or inverted ranges", () => {
    const merged = normaliseRanges(
      [
        { start: 10, end: 14 },
        { start: 2, end: 6 },
        { start: 5, end: 8 },
        { start: 20, end: 20 },
        { start: 9, end: 3 },
      ],
      30,
    );
    expect(merged).toEqual([
      { start: 2, end: 8 },
      { start: 10, end: 14 },
    ]);
  });

  it("clamps ranges to the text length", () => {
    expect(normaliseRanges([{ start: -3, end: 100 }], 10)).toEqual([{ start: 0, end: 10 }]);
  });
});

describe("segmentText", () => {
  it("highlights exactly the quoted words", () => {
    const text = "Primary caregivers receive 16 weeks of fully paid leave. Secondary get 8.";
    const quote = "16 weeks of fully paid leave";
    const start = text.indexOf(quote);
    const segments = segmentText(text, [{ start, end: start + quote.length }]);
    expect(segments.map((s) => s.text).join("")).toBe(text);
    expect(segments.filter((s) => s.highlighted).map((s) => s.text)).toEqual([quote]);
  });

  it("returns the whole text unhighlighted when there is no range", () => {
    expect(segmentText("plain", [])).toEqual([{ text: "plain", highlighted: false }]);
    expect(segmentText("plain", [{ start: 3, end: 3 }])).toEqual([{ text: "plain", highlighted: false }]);
  });

  it("handles a highlight at the very start and the very end", () => {
    expect(segmentText("abcdef", [{ start: 0, end: 2 }]).map((s) => [s.text, s.highlighted])).toEqual([
      ["ab", true],
      ["cdef", false],
    ]);
    expect(segmentText("abcdef", [{ start: 4, end: 6 }]).map((s) => [s.text, s.highlighted])).toEqual([
      ["abcd", false],
      ["ef", true],
    ]);
  });

  it("keeps the highlight on the right words when an emoji comes first (Python offsets are code points)", () => {
    const text = "😀😀 Leave is 16 weeks long.";
    const pythonStart = [...text].indexOf("1"); // what the backend would send
    const pythonEnd = pythonStart + "16 weeks".length;
    const highlighted = segmentText(text, [{ start: pythonStart, end: pythonEnd }]).filter((s) => s.highlighted);
    expect(highlighted.map((s) => s.text)).toEqual(["16 weeks"]);
  });

  it("merges several citations that touch the same chunk", () => {
    const segments = segmentText("one two three four", [
      { start: 0, end: 7 },
      { start: 4, end: 13 },
    ]);
    expect(segments.filter((s) => s.highlighted).map((s) => s.text)).toEqual(["one two three"]);
  });
});
