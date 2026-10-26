import { looksLikeLiteratureQuestion } from "./researchIntent";

describe("looksLikeLiteratureQuestion", () => {
  it.each([
    "Find research papers on sparse attention for long sequences",
    "What does the literature say about remote work and productivity?",
    "Summarize recent studies about battery degradation",
    "Is there an arXiv paper on retrieval augmented generation?",
    "State of the art in speech recognition",
    "What is 10.1038/nature14539 about?",
  ])("suggests published research for: %s", (question) => {
    expect(looksLikeLiteratureQuestion(question)).toBe(true);
  });

  it.each([
    "How many weeks of paid parental leave do primary caregivers get?",
    "What is the nightly hotel limit in major cities?",
    "How quickly must I report a phishing email?",
    "papers",
    "",
  ])("stays quiet for: %s", (question) => {
    expect(looksLikeLiteratureQuestion(question)).toBe(false);
  });
});
