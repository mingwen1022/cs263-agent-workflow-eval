"""Generate lightweight PDF and DOCX source files for the benchmark.

The generated documents are intentionally simple but valid enough for the local
benchmark tools to parse without optional third-party dependencies.
"""

from __future__ import annotations

import html
import textwrap
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data" / "generated" / "hard_v1" / "sources"


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_simple_pdf(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wrapped_lines = [title, ""] + [
        item
        for line in lines
        for item in (textwrap.wrap(line, width=88) or [""])
    ]
    text_ops = ["BT", "/F1 10 Tf", "50 760 Td", "14 TL"]
    for line in wrapped_lines[:50]:
        text_ops.append(f"({_pdf_escape(line)}) Tj")
        text_ops.append("T*")
    text_ops.append("ET")
    stream = "\n".join(text_ops).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(output)


def write_simple_docx(path: Path, title: str, paragraphs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = []
    for paragraph in [title, ""] + paragraphs:
        body.append(
            "<w:p><w:r><w:t xml:space=\"preserve\">"
            + html.escape(paragraph)
            + "</w:t></w:r></w:p>"
        )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + "<w:sectPr/></w:body></w:document>"
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document_xml)


def main() -> None:
    write_simple_pdf(
        DATA_ROOT / "hard_initial_tr19_reimbursement" / "travel_policy_packet.pdf",
        "Travel Policy Packet - Active and Archived Extracts",
        [
            "Page note: this packet contains active rules plus archived reference material.",
            "Reviewer warning: active rules and archived extracts are interleaved in this packet.",
            "ACTIVE POLICY VERSION: 2026.2.",
            "Lodging is reimbursable up to 210.00 per night unless written manager approval authorizes a higher nightly rate for the trip.",
            "Meals are reimbursed at actual cost up to 65.00 per calendar day.",
            "Alcohol is never reimbursable and must be removed before applying the daily meal cap.",
            "Normal commuting between home and the regular office is not reimbursable.",
            "Conference or workshop registration is reimbursable only if pre-approved in writing by a manager.",
            "Premium internet, entertainment, and gifts are not reimbursable unless a separate finance exception says otherwise.",
            "Archived note: version 2025.4 used different meal and lodging caps. It is retained for audit history only.",
            "Noise: airfare rules, passport renewal fees, and relocation stipends are handled by separate teams and do not apply to TR-19.",
            "Noise: a sample catering approval form appears in the appendix. It is not a travel approval.",
            "Noise: TR-18 rental-car approval appears in the scan bundle. It is unrelated to TR-19.",
        ],
    )
    write_simple_docx(
        DATA_ROOT / "hard_initial_tr19_reimbursement" / "approval_packet_tr19.docx",
        "TR-19 Approval Packet",
        [
            "Approved before travel: hotel rate up to 245.00 per night for two nights.",
            "Approved before travel: workshop registration for the April 4 training session.",
            "This approval does not cover premium WiFi, gifts, alcohol, or commuting.",
            "Noise: a separate trip TR-18 had rental-car approval; do not apply it to TR-19.",
            "Noise: a catering pre-approval template appears below but is not part of the travel claim.",
            "Noise: the word approved appears in an email footer for procurement templates; it is not a finance exception.",
            "Clarification: airport rideshare is governed by normal policy and is not a special exception.",
        ],
    )
    write_simple_pdf(
        DATA_ROOT / "hard_vendor_renewal_cb27" / "cloudbox_renewal_packet.pdf",
        "CloudBox Renewal Packet CB-27",
        [
            "Standard plan: 1200.00 base, 100 included seats, 18.00 per additional seat, 5 TB included storage, 90.00 per extra TB.",
            "Premium plan: 2100.00 base, 150 included seats, 12.00 per additional seat, 10 TB included storage, 60.00 per extra TB.",
            "Enterprise plan: 3100.00 base, 300 included seats, 8.00 per additional seat, 25 TB included storage, 40.00 per extra TB.",
            "Renewal amendment: if Premium is renewed by 2026-06-15, apply a 15 percent discount to the Premium monthly base fee.",
            "Noise: a 2025 pilot offered a one-time migration credit, but it expired and should not be used for CB-27.",
            "Noise: EU-region prices are listed in a separate appendix and are not valid for CB-27.",
            "Noise: API call volume appears in usage exports but does not change Standard or Premium prices.",
            "Guidance: choose the least expensive eligible plan that satisfies the support target.",
        ],
    )
    write_simple_docx(
        DATA_ROOT / "hard_vendor_renewal_cb27" / "support_requirement_memo.docx",
        "Operations Support Requirement Memo",
        [
            "For the next term, operations systems must have vendor support response of four hours or better.",
            "A next-business-day target is not acceptable for this team.",
            "Noise: analytics-only tools may use email support, but CloudBox is not analytics-only.",
            "Noise: procurement requested a legal review for Enterprise, but no Enterprise recommendation is required if Premium satisfies support and cost goals.",
            "Noise: sandbox environments may use slower support. Production CloudBox usage is the relevant scope.",
            "Clarification: four-hour support satisfies the requirement; one-hour support also satisfies it but may cost more.",
        ],
    )
    write_simple_pdf(
        DATA_ROOT / "hard_incident_sla_ir42" / "incident_sla_packet.pdf",
        "Incident SLA Packet IR-42",
        [
            "Gold customers: acknowledgement must occur within 10 minutes of the first qualifying production alert.",
            "If acknowledgement is more than 15 minutes late beyond the acknowledgement SLA, each affected Gold customer receives a 250.00 service credit.",
            "The public status page should be updated within 30 minutes of the first qualifying alert.",
            "Silver customers: acknowledgement must occur within 30 minutes and no automatic service credit applies for acknowledgement delays under 60 minutes.",
            "Noise: uptime percentage credits are calculated quarterly and are not part of this acknowledgement review.",
            "Noise: staging and sandbox alerts are excluded from the SLA clock.",
            "Noise: suspended accounts are excluded from automatic credits even if listed in customer exports.",
            "Guidance: status-page delay is a risk flag but does not change the acknowledgement credit amount.",
        ],
    )
    write_simple_docx(
        DATA_ROOT / "hard_incident_sla_ir42" / "incident_ops_notes_ir42.docx",
        "Incident Operations Notes IR-42",
        [
            "09:10 PDT: qualifying production alert opened for checkout API errors.",
            "09:24 PDT: support added reports from Aster Bank and Northwind Health.",
            "09:38 PDT: on-call engineer acknowledged the incident.",
            "09:51 PDT: first public status-page update was posted.",
            "Noise: Blue Finch Retail reported impact but is a Silver customer.",
            "Noise: Summit Labs is Gold but was not affected by IR-42.",
            "Noise: a draft status update existed at 09:35 PDT but was not published externally.",
            "Noise: Old Town Media is suspended and should not receive automatic credit.",
        ],
    )


if __name__ == "__main__":
    main()
