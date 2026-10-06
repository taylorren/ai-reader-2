"""Port notes (highlights + AI analyses) from the previous app's database.

The previous build discarded the EPUB and kept a pickle, so the book itself
must be re-uploaded — but its notes live in plain SQLite and port cleanly:
the slug algorithm is unchanged and chapter_index is the canonical key, so
importing under the re-uploaded book's slug restores everything. The old
schema carried no chapter_path/block_id; those rows anchor by selected text.

    python3 scripts/port_notes.py list   --db /path/to/old/reader_data.db
    python3 scripts/port_notes.py export --db /path/to/old/reader_data.db \
        --book-id "书名" -o notes.json
    python3 scripts/port_notes.py import notes.json [--db reader_data.db] \
        [--into 新slug]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_list(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    query = """
        SELECT h.book_id, COUNT(DISTINCT h.id) AS highlights,
               COUNT(a.id) AS analyses
        FROM highlights h LEFT JOIN ai_analyses a ON a.highlight_id = h.id
        GROUP BY h.book_id ORDER BY h.book_id
    """
    for row in conn.execute(query):
        print(f"{row['highlights']:>3} highlights, {row['analyses']:>3} analyses"
              f"  —  {row['book_id']}")
    conn.close()


def cmd_export(args: argparse.Namespace) -> None:
    conn = connect(args.db)
    highlights = [
        dict(row) for row in conn.execute(
            "SELECT * FROM highlights WHERE book_id = ? ORDER BY id",
            (args.book_id,),
        )
    ]
    if not highlights:
        sys.exit(f"no highlights for book_id {args.book_id!r}")
    analyses = [
        dict(row) for row in conn.execute(
            """SELECT a.* FROM ai_analyses a
               JOIN highlights h ON a.highlight_id = h.id
               WHERE h.book_id = ? ORDER BY a.id""",
            (args.book_id,),
        )
    ]
    conn.close()
    payload = {
        "book_id": args.book_id,
        "exported_at": datetime.now().isoformat(),
        "source_db": args.db,
        "highlights": highlights,
        "analyses": analyses,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"exported {len(highlights)} highlights, {len(analyses)} analyses"
          f" -> {out}")


def cmd_import(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.json_file).read_text(encoding="utf-8"))
    old_book_id = payload["book_id"]
    target = args.into or old_book_id

    conn = connect(args.db)
    book = conn.execute("SELECT slug FROM books WHERE slug = ?",
                        (target,)).fetchone()
    if book is None:
        sys.exit(f"target slug {target!r} is not in this database yet —"
                 f" upload the book first (the old book_id was {old_book_id!r})")
    existing = conn.execute(
        "SELECT COUNT(*) FROM highlights WHERE book_id = ?", (target,)
    ).fetchone()[0]
    if existing and not args.force:
        sys.exit(f"{target!r} already has {existing} highlights;"
                 f" use --force to import a second copy regardless")

    id_map: dict[int, int] = {}
    for highlight in payload["highlights"]:
        cursor = conn.execute("""
            INSERT INTO highlights (book_id, chapter_index, chapter_path,
                                    block_id, selected_text, context_before,
                                    context_after, created_at)
            VALUES (?, ?, NULL, NULL, ?, ?, ?, ?)
        """, (target, highlight["chapter_index"], highlight["selected_text"],
              highlight["context_before"], highlight["context_after"],
              highlight["created_at"]))
        id_map[highlight["id"]] = cursor.lastrowid

    count = 0
    for analysis in payload["analyses"]:
        conn.execute("""
            INSERT INTO ai_analyses (highlight_id, analysis_type, prompt,
                                     response, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (id_map[analysis["highlight_id"]], analysis["analysis_type"],
              analysis["prompt"], analysis["response"],
              analysis["created_at"]))
        count += 1
    conn.commit()
    conn.close()
    print(f"imported {len(id_map)} highlights and {count} analyses"
          f" under {target!r} (from {old_book_id!r})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list book_ids with note counts")
    listing.add_argument("--db", required=True)
    listing.set_defaults(func=cmd_list)

    exporter = sub.add_parser("export", help="export one book's notes to JSON")
    exporter.add_argument("--db", required=True)
    exporter.add_argument("--book-id", required=True)
    exporter.add_argument("-o", "--out", required=True)
    exporter.set_defaults(func=cmd_export)

    importer = sub.add_parser("import",
                              help="import a JSON export into this database")
    importer.add_argument("json_file")
    importer.add_argument("--db", default="reader_data.db")
    importer.add_argument("--into",
                          help="target slug if it differs from the old book_id")
    importer.add_argument("--force", action="store_true",
                          help="import even if the target already has notes")
    importer.set_defaults(func=cmd_import)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()