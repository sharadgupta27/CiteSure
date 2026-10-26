import { locateQuote, normalizeRects, squashText } from "./pdfQuote";

describe("squashText", () => {
  it("keeps lower-case letters and digits only and expands ligatures", () => {
    expect(squashText("Oﬃce  “Hours”: 9–5!")).toBe("officehours95");
  });
});

describe("locateQuote", () => {
  const items = ["Primary caregivers receive ", "16 weeks of fully paid leave.", " Secondary caregivers receive 8 weeks."];

  it("finds a quote inside one item and returns its offsets", () => {
    const match = locateQuote(items, "16 weeks of fully paid leave");
    expect(match?.exact).toBe(true);
    expect(match?.spans).toEqual([{ item: 1, start: 0, end: 28 }]);
  });

  it("finds a quote that spans items, ignoring case, spacing and punctuation", () => {
    const match = locateQuote(items, "caregivers  RECEIVE 16 weeks");
    expect(match?.spans.map((s) => s.item)).toEqual([0, 1]);
    expect(match?.spans[0]).toEqual({ item: 0, start: 8, end: 26 });
    expect(match?.spans[1]).toEqual({ item: 1, start: 0, end: 8 });
  });

  it("copes with a word hyphenated across lines", () => {
    const lines = ["The verification step rejects any claim that is not sup-", "ported by the cited passage."];
    const match = locateQuote(lines, "claim that is not supported by the cited passage");
    expect(match?.exact).toBe(true);
    expect(match?.spans.map((s) => s.item)).toEqual([0, 1]);
  });

  it("copes with ligatures in the PDF but not in the quote", () => {
    const match = locateQuote(["The ﬁnal oﬃce policy applies."], "final office policy");
    expect(match?.exact).toBe(true);
    expect(match?.spans).toEqual([{ item: 0, start: 4, end: 20 }]);
  });

  it("handles characters outside the BMP without drifting", () => {
    const match = locateQuote(["😀 smile  then the real quote text"], "the real quote text");
    expect(match?.spans).toEqual([{ item: 0, start: 15, end: 34 }]);
  });

  it("returns null when the quote is not on the page", () => {
    expect(locateQuote(items, "twelve months of unpaid sabbatical")).toBeNull();
  });

  it("does not trust very short quotes", () => {
    expect(locateQuote(items, "of")).toBeNull();
  });

  it("anchors on both ends of a long quote whose middle differs", () => {
    const start = "Employees accrue vacation days monthly during their first year of service";
    const end = "and unused days roll over until the end of the following calendar year";
    const page = [`${start} 1 and are credited on the first working day, ${end}.`];
    const match = locateQuote(page, `${start} and are credited, ${end}`);
    expect(match?.exact).toBe(false);
    expect(match?.spans[0]?.start).toBe(0);
    expect(match?.spans[0]?.end).toBeGreaterThan(start.length);
  });

  it("falls back to the beginning when the end is missing", () => {
    const start = "Employees accrue vacation days monthly during their first year of service";
    const match = locateQuote([start + " somewhere"], `${start} but this tail is not on the page at all, really not`);
    expect(match?.exact).toBe(false);
    expect(match?.spans.length).toBe(1);
  });
});

describe("normalizeRects", () => {
  const box = { left: 100, top: 200, width: 400, height: 800 };

  it("converts to fractions of the page box", () => {
    expect(normalizeRects([{ left: 140, top: 280, width: 200, height: 40 }], box)).toEqual([
      { x: 0.1, y: 0.1, w: 0.5, h: 0.05 },
    ]);
  });

  it("drops slivers, duplicates and clamps to the page", () => {
    const rects = normalizeRects(
      [
        { left: 100, top: 200, width: 0.5, height: 10 },
        { left: 90, top: 200, width: 100, height: 20 },
        { left: 90, top: 200, width: 100, height: 20 },
        { left: 450, top: 990, width: 200, height: 40 },
      ],
      box,
    );
    expect(rects).toHaveLength(2);
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.x + r.w).toBeLessThanOrEqual(1);
      expect(r.y + r.h).toBeLessThanOrEqual(1);
    }
  });

  it("returns nothing for an unmeasured page and honours the maximum", () => {
    expect(normalizeRects([{ left: 0, top: 0, width: 5, height: 5 }], { left: 0, top: 0, width: 0, height: 0 })).toEqual([]);
    const many = Array.from({ length: 10 }, (_, i) => ({ left: 100 + i * 5, top: 200, width: 4, height: 4 }));
    expect(normalizeRects(many, box, 3)).toHaveLength(3);
  });
});
