from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .engine import Segment, TranscriptionResult


def timestamp(seconds: float, srt: bool = False) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if srt else ":"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def markdown_text(result: TranscriptionResult) -> str:
    if not result.segments:
        return f"# Transcription\n\n{result.text}\n"
    blocks = ["# Transcription", ""]
    for segment in result.segments:
        blocks.extend([f"**[{timestamp(segment.start)[:8]}]**", "", segment.text, ""])
    return "\n".join(blocks).rstrip() + "\n"


def srt_text(segments: list[Segment]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n{timestamp(segment.start, True)} --> {timestamp(segment.end, True)}\n{segment.text}"
        )
    return "\n\n".join(blocks).rstrip() + "\n"


def _xml_text(value: str) -> str:
    """Return text that is valid inside an Office Open XML document."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    return escape(cleaned)


def _word_paragraph(text: str, *, bold: bool = False, title: bool = False) -> str:
    properties = ""
    run_properties = ""
    if title:
        properties = '<w:pPr><w:jc w:val="center"/><w:spacing w:after="360"/></w:pPr>'
        run_properties = (
            '<w:rPr><w:b/><w:sz w:val="34"/><w:szCs w:val="34"/>'
            '<w:color w:val="183B4E"/></w:rPr>'
        )
    elif bold:
        properties = '<w:pPr><w:spacing w:before="180" w:after="80"/></w:pPr>'
        run_properties = '<w:rPr><w:b/><w:color w:val="087F6B"/></w:rPr>'
    else:
        properties = '<w:pPr><w:jc w:val="both"/><w:spacing w:after="160"/></w:pPr>'
    return (
        f'<w:p>{properties}<w:r>{run_properties}'
        f'<w:t xml:space="preserve">{_xml_text(text)}</w:t></w:r></w:p>'
    )


def write_docx(result: TranscriptionResult, path: Path) -> None:
    """Create a dependency-free Word document containing the full transcript."""
    paragraphs = [_word_paragraph("Transcription", title=True)]
    if result.segments:
        for segment in result.segments:
            paragraphs.append(_word_paragraph(f"[{timestamp(segment.start)[:8]}]", bold=True))
            paragraphs.append(_word_paragraph(segment.text))
    else:
        text_blocks = [block.strip() for block in result.text.splitlines() if block.strip()]
        for block in text_blocks or [result.text]:
            paragraphs.append(_word_paragraph(block))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>'
        + "".join(paragraphs)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/>'
        '</w:sectPr></w:body></w:document>'
    )
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:title>Transcription VozLocal</dc:title><dc:creator>VozLocal</dc:creator>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>'
        '</cp:coreProperties>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '</Types>'
    )
    package_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '</Relationships>'
    )

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as document:
        document.writestr("[Content_Types].xml", content_types)
        document.writestr("_rels/.rels", package_rels)
        document.writestr("word/document.xml", document_xml)
        document.writestr("docProps/core.xml", core_xml)


def build_exports(
    result: TranscriptionResult,
    stem: str,
    output_dir: Path,
    requested_formats: list[str],
) -> dict[str, Path]:
    safe_stem = "".join(char if char.isalnum() or char in "-_" else "_" for char in stem).strip("_")
    safe_stem = safe_stem or "audio"
    exports: dict[str, Path] = {}
    payloads = {
        "txt": result.text.rstrip() + "\n",
        "md": markdown_text(result),
        "srt": srt_text(result.segments),
    }
    for file_format in requested_formats:
        path = output_dir / f"{safe_stem}_transcription.{file_format}"
        if file_format == "docx":
            write_docx(result, path)
        else:
            path.write_text(payloads[file_format], encoding="utf-8")
        exports[file_format] = path
    return exports
