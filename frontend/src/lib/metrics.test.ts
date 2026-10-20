import { deltaClass, formatDelta, formatMetric } from "./metrics";

describe("metric formatting", () => {
  it("formats values with two decimals and dashes for missing", () => {
    expect(formatMetric(0.8765)).toBe("0.88");
    expect(formatMetric(undefined)).toBe("–");
  });

  it("formats deltas with a sign and treats tiny changes as zero", () => {
    expect(formatDelta(0.0712)).toBe("+0.07");
    expect(formatDelta(-0.2)).toBe("−0.20");
    expect(formatDelta(0.001)).toBe("0.00");
  });

  it("colours improvements green and regressions red", () => {
    expect(deltaClass("mrr", 0.1)).toContain("emerald");
    expect(deltaClass("mrr", -0.1)).toContain("red");
    expect(deltaClass("mrr", 0)).toContain("slate");
  });

  it("knows that fewer wrongful refusals is an improvement", () => {
    expect(deltaClass("answerable_refusal_rate", -0.1)).toContain("emerald");
    expect(deltaClass("answerable_refusal_rate", 0.1)).toContain("red");
  });
});
