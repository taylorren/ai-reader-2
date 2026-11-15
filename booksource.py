"""THE ADAPTER: the only module that imports epubx.

The method is epubx's own MVP reader (its tools/serve.py): open the book,
serve its own files at their own paths, walk the parsed blocks for footnote
edges, extract plain text beside them. Everything here returns plain Python —
dicts, tuples, strings, bytes — and this is the only file that names the
library, so replacing it later touches one module (SPEC.md).

Opening never raises. A file that cannot be read as a book comes back with
`unsupported` naming why, and every accessor then yields nothing — the caller
asks the book, never the exception (principle 7).
"""

from __future__ import annotations

import os
import zipfile

import epubx

# The block kinds whose text can name a page in the sidebar: the same prose a
# highlight anchors to (ANCHOR_KINDS in routers/reader.py), because a caption
# is a line a reader reads — a table, a list or a figure's empty text is not.
LABEL_KINDS = frozenset(
    ("paragraph", "heading", "quote", "preformatted", "definition"))

# A caption is a label, not text: the drawer reads best at one line an entry,
# and a plate's words can run on — a caption and a description under the same
# picture share one block in some books.
TOC_LABEL_CHARS = 48


def _drawer_label(text: str | None) -> str | None:
    """`text` as a drawer label — or None when it is not a reader's words.

    A style block reaches the block walk as prose (two InDesign title pages in
    the corpus put a stylesheet where text would be: '@page {padding: 0pt…}'),
    so the punctuation of markup — braces and semicolons — disqualifies a
    candidate. A label longer than the drawer's line is cut, not wrapped: the
    caption's first clause is what tells one plate from another.
    """
    text = (text or "").strip()
    if not text or text.startswith("@") or any(ch in text for ch in "{};"):
        return None
    if len(text) > TOC_LABEL_CHARS:
        text = text[:TOC_LABEL_CHARS].rstrip() + "…"
    return text


class Book:
    """A book on disk, as the rest of this system sees it.

    Construction never raises and never parses a chapter. The accessors that
    parse a chapter (chapter_text, footnotes, and the word count built on
    chapter_text) are CPU-bound lxml work: under FastAPI they belong in a
    threadpool.
    """

    def __init__(self, path, _book=None, _reason: str | None = None):
        self.path = os.fspath(path)
        self._book = _book
        self._reason = _reason

    # -- opening -----------------------------------------------------------

    @classmethod
    def open(cls, path) -> "Book":
        """Open a book from disk, naming any failure instead of raising it."""
        try:
            return cls(path, _book=epubx.open_book(os.fspath(path)))
        except epubx.EpubError as exc:
            return cls(path, _reason=str(exc))
        except zipfile.BadZipFile as exc:
            return cls(path, _reason=f"not a zip archive: {exc}")
        except OSError as exc:
            return cls(path, _reason=f"unreadable file: {exc}")
        except Exception as exc:  # the adapter boundary: name it, never raise
            return cls(path, _reason=f"unopenable book: {exc}")

    # -- identity ----------------------------------------------------------

    @property
    def unsupported(self) -> str | None:
        """Why this book cannot be rendered, or None. Named, never raised."""
        if self._book is None:
            return self._reason
        return self._book.unsupported

    @property
    def opened(self) -> bool:
        """False when the file could not be opened as a book at all.

        A book that opened but cannot be rendered (DRM, image-only) still
        has `unsupported` set — it is storable, and the reason belongs on
        its library card. A file that never opened has nothing to store.
        """
        return self._book is not None

    @property
    def title(self) -> str | None:
        return self._book.metadata.title if self._book else None

    @property
    def author(self) -> str | None:
        """The book's authors — its `aut` creators, joined."""
        if self._book is None:
            return None
        names = [c.name for c in self._book.metadata.creators if c.role == "aut"]
        return ", ".join(names) or None

    @property
    def language(self) -> str | None:
        return self._book.metadata.language if self._book else None

    @property
    def identifier(self) -> str | None:
        return self._book.metadata.identifier if self._book else None

    @property
    def publisher(self) -> str | None:
        return self._book.metadata.publisher if self._book else None

    @property
    def date(self) -> str | None:
        return self._book.metadata.date if self._book else None

    # -- shape -------------------------------------------------------------

    @property
    def spine(self) -> tuple[str, ...]:
        """The book's content documents, in reading order."""
        return self._book.spine if self._book else ()

    @property
    def chapter_count(self) -> int:
        return len(self.spine)

    @property
    def cover_path(self) -> str | None:
        """The cover image's path inside the book — served from the book itself."""
        cover = self._book.cover if self._book else None
        return cover.path if cover else None

    def toc_json(self) -> list[dict]:
        """The table of contents as a tree of plain dicts (the MVP's shape).

        `outline`, not `toc`: the book's declared navigation with chapters
        filled in from its headings wherever the nav stops short (epubx's
        derived outline). A volume-only NCX then still offers a way into each
        volume.

        The outline claims, implicitly, that the book's navigation names every
        document in its spine — and a real book can contradict it. A
        publisher's photo insert is the case that hid: 自由的窄廊's text points
        the reader at its plates (書中相片集插頁所示) while its nav and its NCX
        leave all fifteen of them out, so the drawer named every chapter and
        the plates were reachable only by paging one document at a time. A
        spine document no declared entry names is listed here anyway when it
        is a plate page — it opens with a picture, and its caption follows —
        at its spine position among the entries around it (see
        `_unlisted_page_label` for the shape, and for what looser rules once
        let into the drawer).

        The work is the outline's own: it already reads every chapter, so the
        caller pays that parse once per book — the same work the reader does
        when it renders the chapter.
        """
        if self._book is None:
            return []

        def shape(nodes) -> list[dict]:
            return [
                {"label": n.label, "href": n.href, "anchor": n.anchor,
                 "children": shape(n.children)}
                for n in nodes
            ]

        return self._with_unlisted_pages(shape(self._book.outline))

    # -- the spine pages the book's own contents never names ------------------

    def _with_unlisted_pages(self, nodes: list[dict]) -> list[dict]:
        """The declared tree with the spine's unlisted plate pages inserted.

        Coverage is by href, so a chapter named only through a heading — an
        anchor entry the outline filled in — counts as named. Each unlisted
        spine document that is a plate page enters just before the declared
        entry that follows it in the spine, so the drawer reads in the book's
        own order: 自由的窄廊's fifteen plates land between 引用書目 and
        版權頁, where the spine has them, not as a foreign tail after the
        book's last entry.
        """
        if self._book is None:
            return nodes

        spine = self._book.spine
        named: set[str] = set()

        def collect(entries):
            for entry in entries:
                if entry["href"]:
                    named.add(entry["href"])
                collect(entry["children"])

        collect(nodes)

        additions: list[tuple[int, dict]] = []
        for index, href in enumerate(spine):
            if href in named:
                continue
            label = self._unlisted_page_label(index)
            if label is not None:
                additions.append((index, {"label": label, "href": href,
                                           "anchor": None, "children": []}))
        if not additions:
            return nodes

        position = {href: where for where, href in enumerate(spine)}
        merged: list[dict] = []
        added = 0
        for entry in nodes:
            where = position.get(entry["href"])
            while (where is not None and added < len(additions)
                   and additions[added][0] < where):
                merged.append(additions[added][1])
                added += 1
            merged.append(entry)
        merged.extend(page for _, page in additions[added:])
        return merged

    def _unlisted_page_label(self, index: int) -> str | None:
        """A spine document the contents never named — if it is a plate page.

        A plate page opens with its picture: the first meaningful block is a
        figure and the caption follows it. That is how the missing plates are
        shaped (自由的窄廊's fifteen 相片集 pages, Mao: The Real Story's photo
        insert, the Innovators' picture sections, the 企鹅欧洲史 volumes'
        gallery pages) — and it is also what keeps the residue out. Measured
        against the 301-book corpus, two looser rules were tried and rejected:
        "any unlisted document, labelled by its first prose" admitted a
        split book's 39 half-sentence fragments ('Therefore , and') and two
        title pages' stylesheets ('@page {padding: 0pt…}'); "a picture with
        words somewhere after it" still admitted 55 split fragments whose
        illustration sits mid-chapter (福尔摩斯探案全集: the label became the
        story sentence that followed the picture), a novel's dialogue chunks,
        Star Wars chapter-number headings, and publisher promo pages whose
        logo leads but whose 'caption' is the blurb. A page that begins with
        its words is a chapter chunk, not an insert — however many pictures
        were dropped into it.

        The head `<title>` reaches the block walk as a leading paragraph (a
        footnote marker hung on the title must not vanish, content.py), so
        the document's own title block is dropped before the first block is
        judged (`_document_title`). Blocks can nest, so the walk is over the
        whole block tree — the library's own idiom (Chapter.footnotes,
        outline.py).
        """
        if self._book is None:
            return None
        chapter = self._book.chapters[index]
        blocks = list(chapter.blocks)
        head_title = self._document_title(chapter.href)
        if (blocks and head_title
                and blocks[0].kind in LABEL_KINDS
                and (blocks[0].text or "").strip() == head_title):
            blocks = blocks[1:]  # the head <title>, not the page's own words
        meaningful = [
            node
            for block in blocks
            for node in block  # nested blocks included
            if node.kind == "figure" or (node.text or "").strip()
        ]
        if not meaningful or meaningful[0].kind != "figure":
            return None
        caption = next(
            (node.text for node in meaningful[1:]
             if node.kind in LABEL_KINDS and (node.text or "").strip()),
            None,
        )
        return _drawer_label(caption)

    def _document_title(self, href: str) -> str | None:
        """The document's own `<head><title>` text, or None.

        Only used to tell the head-title block from the page's own words
        (`_unlisted_page_label`). This is a second parse of the document —
        `Chapter.blocks` cached the block walk, not the element tree — and it
        is paid once per spine page the contents never names: the pages in
        question are plates and dividers, small by nature. The first `title`
        element in document order is the head's.
        """
        if self._book is None:
            return None
        root = self._book.read_parsed(href)
        if root is None:
            return None
        for element in root.iter():
            tag = (element.tag.rsplit("}", 1)[-1].lower()
                   if isinstance(element.tag, str) else "")
            if tag == "title":
                return "".join(element.itertext()).strip() or None
        return None

    # -- the book's own files ----------------------------------------------

    def resource(self, path: str):
        """One of the book's own files: `.media_type` and `.read()`, or None.

        `path` is what the browser asked for; a leading slash, `./` segments
        and percent-encoding are normalised before lookup. Traversal cannot
        escape the book: the normalised path either names one of the book's
        own members or comes back None.
        """
        return self._book.resource(path) if self._book else None

    # -- text and footnote edges -------------------------------------------

    def chapter_text(self, index: int) -> str:
        """The chapter's extracted plain text — AI context, counts, search.

        An index the spine does not have raises IndexError: that is a caller
        bug, not a book failure, and the router validates against the spine.
        """
        if self._book is None:
            return ""
        return self._book.chapters[index].plain_text

    def blocks(self, index: int) -> list[dict]:
        """The chapter's content blocks: id, kind, text, dom_ids.

        The ids are the library's positional anchors — `{chapter}/b{ordinal}`
        — so a highlight can name the block it belongs to rather than only
        the words it selected (SPEC.md principle 5). The served document
        carries none of these ids, so a reader locates the block by matching
        text; the id is what is stored.
        """
        if self._book is None:
            return []
        return [
            {
                "id": block.id,
                "kind": block.kind,
                "text": block.text,
                "dom_ids": list(block.attributes.get("dom_ids", ())),
            }
            for block in self._book.chapters[index].blocks
        ]

    def footnotes(self, index: int) -> list[dict]:
        """The chapter's footnote edges, normalized by the library.

        The library recognizes the book's own footnote signals — semantic
        ref types, footnote classes, and the compact ids of Word/Calibre
        pipelines — and resolves each marker to the note it opens. The edge
        carries the note's text (a note that runs on for several paragraphs
        is gathered whole by the library) and the target's book-internal
        path, so a reader opens a note without fetching a rendered page.
        Markers the library cannot recognize yield no edges; the book's own
        links still work natively.
        """
        if self._book is None:
            return []
        edges = []
        for note in self._book.chapters[index].footnotes:
            target_href = None
            target_anchor = None
            if note.target_id is not None:
                target_href = self._book.chapters[note.target_chapter].href
                if note.target_dom_ids:
                    target_anchor = note.target_dom_ids[0]
            edges.append({
                "block_id": note.block_id,
                "text": note.text,
                "href": note.href,
                "resolved": note.target_id is not None,
                "target_chapter": note.target_chapter,
                "target_href": target_href,
                "target_anchor": target_anchor,
                "target_text": note.note_text,
            })
        return edges

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """Release the file handle. Cached books are closed on eviction."""
        if self._book is not None:
            self._book.close()
            self._book = None

    def __repr__(self) -> str:  # pragma: no cover - convenience
        name = os.path.basename(self.path)
        if self._book is None:
            return f"<Book {name!r} unopenable>"
        return f"<Book {name!r} chapters={self.chapter_count}>"