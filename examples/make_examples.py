"""Builds the binary sample files (DOCX, PDF) for the fictional Fernhollow Bicycle Works. The outputs are committed, so
nobody has to run this; run it after changing the text below:

    cd backend && uv run python ../examples/make_examples.py

python-docx and PyMuPDF are already backend dependencies. The Markdown samples are edited by hand.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
from docx import Document

ROOT = Path(__file__).resolve().parent / "inbox" / "fernhollow-bicycle-works"
NOTICE = "Fictional sample data for CiteSure. Fernhollow Bicycle Works is an invented company."

Section = tuple[str, list[str]]  # heading, paragraphs


def write_docx(
    path: Path, title: str, classification: str, sections: list[Section], table: list[list[str]] | None = None
) -> None:
    doc = Document()
    doc.core_properties.title = title
    doc.core_properties.author = "Fernhollow Bicycle Works (fictional)"
    doc.add_heading(title, level=1)
    doc.add_paragraph(f"{NOTICE} Classification: {classification}.")
    for heading, paragraphs in sections:
        doc.add_heading(heading, level=2)
        for text in paragraphs:
            doc.add_paragraph(text)
    if table:
        grid = doc.add_table(rows=0, cols=len(table[0]))
        grid.style = "Table Grid"
        for row in table:
            cells = grid.add_row().cells
            for cell, value in zip(cells, row, strict=True):
                cell.text = value
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def write_pdf(path: Path, title: str, classification: str, sections: list[Section]) -> None:
    doc = pymupdf.open()
    doc.set_metadata({"title": title, "author": "Fernhollow Bicycle Works (fictional)"})
    blocks = [(title, 16.0), (f"{NOTICE} Classification: {classification}.", 9.0)]
    for heading, paragraphs in sections:
        blocks.append((heading, 13.0))
        blocks += [(text, 11.0) for text in paragraphs]

    page, y = doc.new_page(), 72.0
    for text, size in blocks:
        height = size * 1.45 * (1 + len(text) * size * 0.5 // 468)  # rough line count for a 468 pt column
        if y + height > 760:
            page, y = doc.new_page(), 72.0
        rect = pymupdf.Rect(72, y, 540, y + height + size * 2)
        spare = page.insert_textbox(rect, text, fontsize=size, fontname="helv")
        y = rect.y1 - max(spare, 0) + size * 0.8
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()


def main() -> None:
    write_docx(
        ROOT / "Handbook" / "travel-and-expenses.docx",
        "Travel and Expenses Policy",
        "Internal",
        [
            (
                "Booking travel",
                [
                    "Book all work travel through the travel desk at travel@fernhollow.example at least 10 working days "
                    "before departure where possible.",
                    "Take economy class for flights under 6 hours. Premium economy is allowed for flights of 6 hours or "
                    "more, with approval from a director.",
                    "Use standard-class rail tickets. First class is allowed only when it costs less than standard class.",
                ],
            ),
            (
                "Hotels and meals",
                [
                    "The hotel limit is £140 per night in the UK and £180 per night in London, including breakfast.",
                    "The daily meal allowance (per diem) is £45 in the UK and €60 in the European Union. Alcohol is not "
                    "reimbursed.",
                ],
            ),
            (
                "Mileage",
                [
                    "Using your own car for work trips is reimbursed at 45p per mile for the first 10,000 miles in a tax "
                    "year and 25p per mile after that. Using your own bicycle is reimbursed at 20p per mile.",
                ],
            ),
            (
                "Claiming expenses",
                [
                    "Submit expense claims in the finance system within 30 days of the trip. Claims submitted later than "
                    "90 days are rejected.",
                    "Attach a receipt for every item over £10. Claims above £500 need approval from your manager and the "
                    "finance business partner.",
                ],
            ),
        ],
    )

    write_docx(
        ROOT / "Finance-Confidential" / "salary-bands-2026.docx",
        "Salary Bands 2026",
        "Restricted, Finance group only",
        [
            (
                "How the bands work",
                [
                    "Salary bands apply from 1 April 2026 and are reviewed every year in March. New hires normally start "
                    "in the lower half of their band. Moving above the band maximum needs approval from the Finance "
                    "Director and the Head of People Operations.",
                    "The annual pay review budget for 2026 is 4.5 percent of the total salary bill.",
                ],
            ),
            ("Bands (annual base salary, GBP)", []),
        ],
        table=[
            ["Band", "Example roles", "Minimum", "Maximum"],
            ["B1", "Assembly technician, warehouse operative", "£25,500", "£31,000"],
            ["B2", "Senior technician, customer support specialist", "£30,000", "£38,500"],
            ["B3", "Design engineer, test engineer, accountant", "£38,000", "£52,000"],
            ["B4", "Senior engineer, product manager", "£50,000", "£68,000"],
            ["B5", "Engineering manager, finance manager", "£65,000", "£88,000"],
            ["B6", "Director", "£85,000", "£125,000"],
        ],
    )

    write_pdf(
        ROOT / "Engineering" / "supplier-quality-agreement.pdf",
        "Supplier Quality Agreement: Ardent Tube Co. (summary)",
        "Confidential, Engineering only",
        [
            (
                "Scope",
                [
                    "This agreement covers the 6061 and 7005 aluminium frame tubes that Ardent Tube Co., a fictional "
                    "supplier, delivers to the Fernhollow frame shop. It took effect on 1 April 2026.",
                ],
            ),
            (
                "Quality targets",
                [
                    "The delivered defect rate must stay at or below 0.5 percent of tubes per quarter.",
                    "Every new or changed tube needs an approved PPAP (production part approval) package before the first "
                    "production delivery.",
                    "Incoming inspection samples each delivery at AQL 1.0. Wall thickness must be within plus or minus "
                    "0.05 mm of the drawing.",
                ],
            ),
            (
                "Handling defects",
                [
                    "When Fernhollow reports a defect, the supplier sends a containment plan within 24 hours and a complete "
                    "8D report within 10 working days.",
                    "If the defect rate is above 0.5 percent for two quarters in a row, the supplier is placed on "
                    "controlled shipping at its own cost until the rate is back on target.",
                ],
            ),
        ],
    )

    write_pdf(
        ROOT / "Finance-Confidential" / "vendor-contract-summary.pdf",
        "Vendor Contract Summary: Ardent Tube Co.",
        "Confidential, Finance group only",
        [
            (
                "Commercial terms",
                [
                    "The contract runs for three years, from 1 April 2026 to 31 March 2029. The expected spend is £1.2 "
                    "million per year.",
                    "Tube prices are fixed for the first year and reviewed every 1 April against the published aluminium "
                    "price index. A price change is capped at 4 percent per year.",
                    "Payment terms are 60 days from the end of the month of delivery.",
                ],
            ),
            (
                "Termination",
                [
                    "Either party may end the contract with 90 days written notice after the first year.",
                    "Fernhollow may end the contract immediately if the supplier stays on controlled shipping for more "
                    "than two quarters.",
                ],
            ),
            (
                "Contacts",
                [
                    "Contract owner: Finance Director. Day-to-day contact: Purchasing, purchasing@fernhollow.example.",
                ],
            ),
        ],
    )
    for path in sorted(ROOT.rglob("*")):
        if path.is_file():
            print(path.relative_to(ROOT.parent), path.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
