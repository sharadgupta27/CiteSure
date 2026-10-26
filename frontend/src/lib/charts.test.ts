import { formatMs, formatPercent, formatUsd, niceMax, shortDate, stackedBars } from "./charts";

describe("niceMax", () => {
  it("rounds up to 1, 2 or 5 times a power of ten", () => {
    expect([0, 1, 3, 4.2, 7, 12, 160, 999].map(niceMax)).toEqual([1, 1, 5, 5, 10, 20, 200, 1000]);
  });
});

describe("formatters", () => {
  it("shows rates, latencies and money in a readable way", () => {
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(0.025)).toBe("2.5%");
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(null)).toBe("n/a");
    expect(formatMs(850.4)).toBe("850 ms");
    expect(formatMs(2400)).toBe("2.4 s");
    expect(formatMs(null)).toBe("n/a");
    expect(formatUsd(0)).toBe("$0");
    expect(formatUsd(0.0012)).toBe("$0.0012");
    expect(formatUsd(12.345)).toBe("$12.35");
  });

  it("formats a date without shifting the day", () => {
    expect(shortDate("2026-10-25")).toBe("Oct 25");
  });
});

describe("stackedBars", () => {
  it("scales bars against a round top and keeps them inside their slot", () => {
    const { bars, top } = stackedBars(
      [
        { date: "2026-10-24", answered: 3, refused: 1 },
        { date: "2026-10-25", answered: 0, refused: 0 },
      ],
      200,
      100,
    );
    expect(top).toBe(5);
    expect(bars[0]!.answeredHeight).toBeCloseTo(60);
    expect(bars[0]!.refusedHeight).toBeCloseTo(20);
    expect(bars[1]!.total).toBe(0);
    expect(bars[0]!.x + bars[0]!.width).toBeLessThanOrEqual(100);
    expect(bars[1]!.x).toBeGreaterThanOrEqual(100);
  });

  it("copes with no data", () => {
    expect(stackedBars([], 100, 50)).toEqual({ bars: [], top: 1 });
  });
});
