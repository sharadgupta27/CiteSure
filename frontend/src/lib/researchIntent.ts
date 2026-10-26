const LITERATURE_PHRASES = [
  /\b(research|scientific|academic) (papers?|articles?|literature|studies)\b/i,
  /\b(papers?|articles?|studies|literature|publications?) (on|about|regarding|related to)\b/i,
  /\bliterature (review|survey|search)\b/i,
  /\b(state[- ]of[- ]the[- ]art|sota|survey of)\b/i,
  /\b(arxiv|openalex|pubmed|crossref|semantic scholar|google scholar|doi:|10\.\d{4,9}\/)/i,
  /\b(peer[- ]reviewed|published (research|work|findings)|preprints?)\b/i,
  /\b(find|search|look up|recommend|list|summari[sz]e)\b.{0,40}\b(papers?|articles?|studies|publications?)\b/i,
  /\bwhat (does|do) (the )?(research|literature|studies|science) (say|show|suggest)\b/i,
];

/**
 * True when a question reads like a request for published research rather than for the company's own documents.
 * Only ever used to suggest widening the search: the user decides, because widening sends keywords outside.
 */
export function looksLikeLiteratureQuestion(question: string): boolean {
  const text = question.trim();
  return text.length >= 12 && LITERATURE_PHRASES.some((pattern) => pattern.test(text));
}
