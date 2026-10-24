import { answer, citation, claim } from "../test/factories";
import { describeLocation, numberCitations } from "./citations";

describe("numberCitations", () => {
  it("numbers sources in order of first appearance", () => {
    const a = citation({ chunk_id: "a", quote_start: 0, quote_end: 5 });
    const b = citation({ chunk_id: "b", quote_start: 10, quote_end: 20 });
    const result = numberCitations(answer({ claims: [claim("First.", [a]), claim("Second.", [b])] }));
    expect(result.claims.map((c) => c.numbers)).toEqual([[1], [2]]);
    expect(result.sources.map((s) => s.citation.chunk_id)).toEqual(["a", "b"]);
  });

  it("gives the same source one number when two claims cite it", () => {
    const a = citation({ chunk_id: "a" });
    const result = numberCitations(answer({ claims: [claim("One.", [a]), claim("Two.", [a])] }));
    expect(result.claims.map((c) => c.numbers)).toEqual([[1], [1]]);
    expect(result.sources).toHaveLength(1);
  });

  it("treats different quotes from one chunk as different sources", () => {
    const result = numberCitations(
      answer({ claims: [claim("x", [citation({ quote_start: 0, quote_end: 4 }), citation({ quote_start: 9, quote_end: 14 })])] }),
    );
    expect(result.claims[0]?.numbers).toEqual([1, 2]);
  });

  it("does not repeat a number within one claim", () => {
    const a = citation();
    expect(numberCitations(answer({ claims: [claim("x", [a, a])] })).claims[0]?.numbers).toEqual([1]);
  });

  it("returns nothing for an answer without claims", () => {
    expect(numberCitations(answer({ claims: [] }))).toEqual({ claims: [], sources: [] });
  });
});

describe("describeLocation", () => {
  it("shows document, last heading and a single page", () => {
    expect(describeLocation(citation({ page_start: 3, page_end: 3 }))).toBe("Parental Leave Policy › How much leave you get (p. 3)");
  });

  it("shows a page range", () => {
    expect(describeLocation(citation({ heading_path: [], page_start: 2, page_end: 4 }))).toBe("Parental Leave Policy (pp. 2–4)");
  });

  it("omits what it does not know", () => {
    expect(describeLocation(citation({ heading_path: [], page_start: null, page_end: null }))).toBe("Parental Leave Policy");
  });
});

describe("public citations", () => {
  it("describes a public source by title and host", () => {
    expect(describeLocation({ ...citation(), document_title: "A Paper", source_type: "public", url: "https://www.arxiv.org/abs/1" })).toBe("A Paper · arxiv.org");
    expect(describeLocation({ ...citation(), document_title: "A Paper", source_type: "public", url: null })).toBe("A Paper");
  });

  it("only allows http(s) addresses as links", async () => {
    const { safeHref, hostOf } = await import("./citations");
    expect(safeHref("https://example.org/x")).toBe("https://example.org/x");
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<script>")).toBeNull();
    expect(safeHref("not a url")).toBeNull();
    expect(safeHref(null)).toBeNull();
    expect(hostOf("nonsense")).toBe("");
  });
});
