"""THROW-AWAY: translate migrated highlight positions onto this app's spine.

The rows `scripts/port_notes.py` imported from ai-reader carry *that* app's
`chapter_index` — derived from its own (ebooklib-era) spine. Where the two
spines disagree, a highlight's "在书中定位" lands on the wrong chapter. This
one-off script rewrites each affected row to the chapter that actually holds
its text, and fills in `chapter_path` / `block_id` (which the old schema never
had) so the row anchors by identity from then on.

It is idempotent and safe to re-run. Dry-run by default.

    uv run python scripts/translate_positions.py                 # report only
    uv run python scripts/translate_positions.py --apply         # write
    uv run python scripts/translate_positions.py --book-id "项狄传 (...)" --apply

Delete this file once the data is translated; it is not part of the app.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from booksource import Book  # noqa: E402

BOOKS_DIR = REPO_ROOT / "books"


def norm(text: str) -> str:
    """Whitespace-insensitive form: the old app's spacing may differ."""
    return re.sub(r"\s+", " ", text or "").strip()


class BookTexts:
    """Lazily parsed chapter texts and block ids for one book."""

    def __init__(self, book: Book):
        self.book = book
        self._texts: dict[int, str] = {}
        self._blocks: dict[int, list[dict]] = {}

    def text(self, index: int) -> str:
        if index not in self._texts:
            self._texts[index] = self.book.chapter_text(index)
        return self._texts[index]

    def blocks(self, index: int) -> list[dict]:
        if index not in self._blocks:
            self._blocks[index] = self.book.blocks(index)
        return self._blocks[index]

    def locate(self, needle: str) -> int | None:
        """The first chapter whose text holds `needle`, or None."""
        target = norm(needle)
        if not target:
            return None
        for index in range(self.book.chapter_count):
            if target in norm(self.text(index)):
                return index
        return None

    def block_for(self, index: int, needle: str) -> str | None:
        """The smallest block of a chapter that holds `needle`."""
        target = norm(needle)
        best = None
        for block in self.blocks(index):
            if target and target in norm(block["text"]):
                if best is None or len(block["text"]) < len(best["text"]):
                    best = block
        return best["id"] if best else None


def translate(db_path: Path, book_id: str | None, apply: bool) -> int:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    books = list(connection.execute("SELECT slug, path FROM books"))
    if book_id:
        books = [row for row in books if row["slug"] == book_id]
    if not books:
        print("no matching books")
        return 0

    changed = 0
    for row in books:
        slug = row["slug"]
        book_path = BOOKS_DIR / row["path"]
        highlights = list(connection.execute(
            "SELECT id, chapter_index, chapter_path, block_id, selected_text "
            "FROM highlights WHERE book_id = ? ORDER BY id", (slug,)))
        if not highlights:
            continue
        if not book_path.exists():
            print(f"!! {slug}: book file missing at {book_path}; skipping")
            continue

        book = Book.open(book_path)
        if book.unsupported:
            print(f"!! {slug}: {book.unsupported}; skipping")
            continue
        texts = BookTexts(book)
        print(f"\n== {slug}  ({book.chapter_count} chapters, {len(highlights)} highlights)")

        for highlight in highlights:
            needle = (highlight["selected_text"] or "").strip()
            stored = highlight["chapter_index"]
            chapter = stored
            if norm(needle) not in norm(texts.text(stored)):
                located = texts.locate(needle)
                if located is None:
                    print(f"  id={highlight['id']}: text not found in any chapter — left alone")
                    continue
                chapter = located
            block_id = highlight["block_id"] or texts.block_for(chapter, needle)
            chapter_path = highlight["chapter_path"] or book.spine[chapter]

            moves = []
            if chapter != stored:
                moves.append(f"chapter {stored} -> {chapter}")
            if block_id != highlight["block_id"]:
                moves.append(f"block {highlight['block_id']} -> {block_id}")
            if chapter_path != highlight["chapter_path"]:
                moves.append(f"path -> {chapter_path}")
            if not moves:
                continue
            changed += 1
            print(f"  id={highlight['id']}: " + "; ".join(moves))
            if apply:
                connection.execute(
                    "UPDATE highlights SET chapter_index = ?, chapter_path = ?, "
                    "block_id = ? WHERE id = ?",
                    (chapter, chapter_path, block_id, highlight["id"]))

    if apply:
        connection.commit()
        print(f"\napplied: {changed} row(s) updated")
    else:
        print(f"\ndry-run: {changed} row(s) would change (re-run with --apply)")
    connection.close()
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO_ROOT / "reader_data.db"))
    parser.add_argument("--book-id", default=None,
                        help="one book's slug; default: every book with highlights")
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default: report only)")
    args = parser.parse_args()
    translate(Path(args.db), args.book_id, args.apply)


if __name__ == "__main__":
    main()
