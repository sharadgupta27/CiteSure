import type { Answer, Citation } from "../api/client";

export interface NumberedSource {
  number: number;
  citation: Citation;
}

export interface NumberedClaim {
  text: string;
  numbers: number[];
}

/**
 * Number the sources of an answer in order of first appearance, so the reader sees [1], [2]... under the answer.
 * The same chunk + quote cited by two claims gets one number.
 */
export function numberCitations(answer: Pick<Answer, "claims">): { claims: NumberedClaim[]; sources: NumberedSource[] } {
  const sources: NumberedSource[] = [];
  const index = new Map<string, number>();
  const claims = answer.claims.map((claim) => {
    const numbers: number[] = [];
    for (const citation of claim.citations) {
      const key = `${citation.chunk_id}:${citation.quote_start}:${citation.quote_end}`;
      let number = index.get(key);
      if (number === undefined) {
        number = sources.length + 1;
        index.set(key, number);
        sources.push({ number, citation });
      }
      if (!numbers.includes(number)) numbers.push(number);
    }
    return { text: claim.text, numbers };
  });
  return { claims, sources };
}

/** "Parental Leave Policy > How much leave you get (p. 2)" */
export function describeLocation(
  citation: Pick<Citation, "document_title" | "heading_path" | "page_start" | "page_end"> & Partial<Pick<Citation, "source_type" | "url">>,
): string {
  if (citation.source_type === "public") return `${citation.document_title}${hostOf(citation.url) ? ` · ${hostOf(citation.url)}` : ""}`;
  const section = citation.heading_path.length > 0 ? ` › ${citation.heading_path[citation.heading_path.length - 1]}` : "";
  let page = "";
  if (citation.page_start != null) {
    page = citation.page_end != null && citation.page_end !== citation.page_start ? ` (pp. ${citation.page_start}–${citation.page_end})` : ` (p. ${citation.page_start})`;
  }
  return `${citation.document_title}${section}${page}`;
}

/** "arxiv.org" for a public citation's address; empty when the address is missing or not a URL. */
export function hostOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Only http(s) addresses may become links: an `url` from a public source is data, never trusted markup. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}
