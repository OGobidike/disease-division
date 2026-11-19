"""The stacks: Zuma Air's help pages, read from kb/ and cut into passages.

Each page is a Markdown file that starts with a small TOML header between two `+++` lines:

    +++
    id = "cabin-baggage"
    title = "Cabin baggage"
    source = "staff"
    visibility = "public"
    +++

`source` says where the page came from: written by Zuma Air staff, taken from the public web,
or received by email. `visibility` says who may read it: anyone, or Zuma Air staff only.
Both labels are what the defenses in Phase 4 work with.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

SOURCES = ("staff", "web", "email")
VISIBILITIES = ("public", "staff")
HEADER_KEYS = {"id", "title", "source", "visibility"}

# Every staff-only page carries its own control number, written at the end of every section,
# so whichever passage is retrieved carries it. If one ever shows up in an answer to a member
# of the public, a staff-only page has leaked.
CONTROL_NUMBER = re.compile(r"ZA-DC-\d{4}")


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    source: str
    visibility: str
    body: str


@dataclass(frozen=True)
class Passage:
    """One section of a page: the unit that search finds and the model reads."""

    id: str
    doc_id: str
    title: str
    heading: str
    text: str

    @property
    def searchable(self) -> str:
        # The page title and section heading travel with every passage, so a section that
        # says "It costs NGN 6,000" still carries what "it" is.
        return "\n".join(part for part in (self.title, self.heading, self.text) if part)


def parse_document(raw: str, name: str = "<page>") -> Document:
    """Read one page: the TOML header, then the Markdown body."""
    text = raw.replace("\r\n", "\n")
    if not text.startswith("+++\n"):
        raise ValueError(f"{name}: a page must start with a +++ header")
    end = text.find("\n+++\n", 4)
    if end == -1:
        raise ValueError(f"{name}: the +++ header is never closed")
    try:
        header = tomllib.loads(text[4:end])
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{name}: the header is not valid TOML ({error})") from None

    missing = HEADER_KEYS - header.keys()
    extra = header.keys() - HEADER_KEYS
    if missing or extra:
        raise ValueError(
            f"{name}: the header needs exactly {sorted(HEADER_KEYS)}; "
            f"missing {sorted(missing)}, unexpected {sorted(extra)}"
        )
    if header["source"] not in SOURCES:
        raise ValueError(f"{name}: source must be one of {SOURCES}, not {header['source']!r}")
    if header["visibility"] not in VISIBILITIES:
        raise ValueError(
            f"{name}: visibility must be one of {VISIBILITIES}, not {header['visibility']!r}"
        )

    body = text[end + len("\n+++\n") :].strip()
    if not body:
        raise ValueError(f"{name}: the page has no text")
    return Document(
        id=header["id"],
        title=header["title"],
        source=header["source"],
        visibility=header["visibility"],
        body=body,
    )


def load_documents(folder: Path) -> list[Document]:
    """Read every page in the folder, sorted by file name."""
    documents = []
    for path in sorted(Path(folder).glob("*.md")):
        document = parse_document(path.read_text(encoding="utf-8"), path.name)
        if document.id != path.stem:
            raise ValueError(f"{path.name}: id {document.id!r} must match the file name")
        documents.append(document)
    if not documents:
        raise ValueError(f"{folder}: no pages found")
    seen = set()
    for document in documents:
        if document.id in seen:
            raise ValueError(f"two pages share the id {document.id!r}")
        seen.add(document.id)
    return documents


def split_passages(document: Document) -> list[Passage]:
    """Cut a page at its `## ` headings. Text before the first heading is its own passage."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in document.body.split("\n"):
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        else:
            sections[-1][1].append(line)

    passages = []
    for heading, lines in sections:
        text = "\n".join(lines).strip()
        if text:
            passages.append(
                Passage(
                    id=f"{document.id}#{len(passages) + 1}",
                    doc_id=document.id,
                    title=document.title,
                    heading=heading,
                    text=text,
                )
            )
    return passages


def all_passages(documents: list[Document]) -> list[Passage]:
    return [passage for document in documents for passage in split_passages(document)]
