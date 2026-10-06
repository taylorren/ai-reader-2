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
        """The table of contents as a tree of plain dicts (the MVP's shape)."""
        if self._book is None:
            return []

        def shape(nodes) -> list[dict]:
            return [
                {"label": n.label, "href": n.href, "anchor": n.anchor,
                 "children": shape(n.children)}
                for n in nodes
            ]

        return shape(self._book.toc)

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

    def footnotes(self, index: int) -> list[dict]:
        """Every footnote marker in a chapter, with the block it resolves to.

        The MVP's method: the marker may sit in one document and its note in
        another, and the library has already resolved that edge to a block
        id. The edge here also carries the note's text and the target's
        book-internal path, so a reader can open a note without fetching a
        rendered page.
        """
        if self._book is None:
            return []
        edges = []
        for block in self._book.chapters[index].blocks:
            for node in block:  # Block.__iter__ walks nested blocks too
                if node.kind != "footnote_ref":
                    continue
                target = node.attributes.get("target_id")
                edge = {
                    "block_id": node.id,
                    "text": node.text,
                    "href": node.attributes.get("href"),
                    "resolved": bool(target),
                    "target_chapter": None,
                    "target_href": None,
                    "target_anchor": None,
                    "target_text": None,
                }
                if target:
                    # The MVP's parse: the block id is cNNNN/bMMMM.
                    target_index = int(target[1:5])
                    target_chapter = self._book.chapters[target_index]
                    target_block = target_chapter.block_by_id(target)
                    dom_ids = (target_block.attributes.get("dom_ids") or ()) if target_block else ()
                    edge["target_chapter"] = target_index
                    edge["target_href"] = target_chapter.href
                    edge["target_anchor"] = dom_ids[0] if dom_ids else None
                    edge["target_text"] = (
                        target_block.plain_text if target_block else None
                    )
                edges.append(edge)
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