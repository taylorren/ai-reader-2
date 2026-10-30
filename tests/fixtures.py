"""Synthetic EPUB fixtures for ai-reader-2.

The same approach as epubx's tests/fixtures.py: tiny books built in tmp
directories, so the suite runs in CI with no real books present. Real-book
behaviour is exercised by test_corpus.py, which skips when EPUBX_CORPUS is
unset.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
              media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

# Stand-in image bytes: the magic numbers are real, so a test can tell a
# JPEG from a PNG, and the adapter hands them over untouched.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 16
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 24

OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fixture Book</dc:title>
    <dc:creator>Jane Doe</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:fixture-0001</dc:identifier>
    <dc:publisher>Fixture Press</dc:publisher>
    <dc:date>2020-01-02</dc:date>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="cover" href="img/cover.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="plate" href="img/plate%20one.png" media-type="image/png"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
    <itemref idref="c2"/>
  </spine>
</package>
"""

NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <ol>
      <li><a href="ch1.xhtml">Chapter One</a></li>
      <li><a href="ch2.xhtml">Chapter Two</a></li>
    </ol>
  </nav>
</body>
</html>
"""

# Chapter one carries the three footnote shapes the reader must handle: a
# note in the same document, an endnote in another chapter, and a reference
# the book never defines. Each marker ends its paragraph, so the marker's
# printed text is exactly its digit. The percent-encoded image reference
# exercises the reader's file route.
CHAPTER_1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Chapter One</title><link rel="stylesheet" href="style.css"/></head>
<body>
  <h1 id="top">Chapter One</h1>
  <p>The first paragraph mentions a plate
     <img src="img/plate%20one.png" alt="A plate" width="40"/> and then keeps
     going for a while, so that this chapter plainly carries real prose and is
     never mistaken for a page of pictures; a reader should see the sentence
     through to its natural end before anything else happens in it.</p>
  <p>A note in this very chapter<a epub:type="noteref" href="#local-note">1</a></p>
  <p>An endnote in chapter two<a epub:type="noteref" href="ch2.xhtml#endnote-1">2</a></p>
  <p>A reference to a note the book never defines<a epub:type="noteref" href="ch2.xhtml#no-such-note">3</a></p>
  <div id="local-note" epub:type="footnote"><p>The local note.</p></div>
  <!-- A blank line, the CJK/InDesign way: a <p> holding only U+3000. epubx
       reports it with text=None — the same value an uncaptioned figure
       carries — so the reader's block filter must tolerate a text-less
       paragraph. Appended last on purpose: the block ids above are the ones
       stored highlights use, and appending cannot renumber them. -->
  <p>　</p>
</body>
</html>
"""

CHAPTER_2 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Chapter Two</title></head>
<body>
  <h1 id="top">Chapter Two</h1>
  <p>Chapter two opens with a little prose of its own, enough characters that
     the detector sees a text book and not a scan, and it keeps talking until
     the threshold is comfortably behind it.</p>
  <div id="endnote-1" epub:type="footnote"><p>The endnote text.</p></div>
</body>
</html>
"""

COUNTING_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head></head>
<body>
  <p>Hello world 汉字</p>
</body>
</html>
"""


def write_epub(path, title: str | None = None) -> Path:
    """A two-chapter book with footnotes, an image, CSS, a cover and a nav TOC.

    `title` overrides the OPF's `<dc:title>`. The slug is the title verbatim,
    so passing `C# in Depth` or `100% Pure` is how a test reaches the
    URL-hostile case (REVIEW P1-2 / T2). The title is XML-escaped, so `&` and
    `<` are safe to pass.
    """
    opf = OPF
    if title is not None:
        opf = OPF.replace("<dc:title>Fixture Book</dc:title>",
                          f"<dc:title>{escape(title)}</dc:title>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first and stored, per the OCF spec.
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/nav.xhtml", NAV)
        zf.writestr("OEBPS/style.css", "body { margin: 0; }")
        zf.writestr("OEBPS/ch1.xhtml", CHAPTER_1)
        zf.writestr("OEBPS/ch2.xhtml", CHAPTER_2)
        zf.writestr("OEBPS/img/cover.jpg", JPEG)
        zf.writestr("OEBPS/img/plate one.png", PNG)
    return Path(path)


def write_counting_epub(path, text: str = "Hello world 汉字") -> Path:
    """A one-chapter book whose text is exactly `text`."""
    chapter = COUNTING_CHAPTER.replace("Hello world 汉字", escape(text))
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Counting Book</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="id">urn:uuid:counting</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="c.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/c.xhtml", chapter)
    return Path(path)


# One chapter, and a nav that names two sections *inside* it. epubx strips the
# fragment from the nav href (nav.py), so all three TOC entries reach the shell
# with the same `href` and differ only in `anchor` — the shape that stranded the
# reader's TOC highlight on the chapter's own entry.
SECTIONED_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Sectioned Book</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:sectioned-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""

SECTIONED_NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <ol>
      <li><a href="ch1.xhtml">Sectioned Book</a>
        <ol>
          <li><a href="ch1.xhtml#sec-a">First Section</a></li>
          <li><a href="ch1.xhtml#sec-b">Second Section</a></li>
        </ol>
      </li>
    </ol>
  </nav>
</body>
</html>
"""

SECTIONED_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Sectioned Book</title></head>
<body>
  <h1 id="top">Sectioned Book</h1>
  <p>The chapter opens with a paragraph of its own, long enough that the text
     detector sees a real book and not a page of pictures, and it keeps going
     until the threshold is comfortably behind it.</p>
  <h2 id="sec-a">First Section</h2>
  <p>The first section's prose lives between its heading and the next one, so a
     reader scrolling through the chapter passes it in the order the contents
     names.</p>
  <h2 id="sec-b">Second Section</h2>
  <p>The second section follows, and its heading is the last one in the
     document — the deepest point a reader can reach in this chapter.</p>
</body>
</html>
"""


def write_sectioned_epub(path) -> Path:
    """A book whose contents names sections inside its single chapter."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", SECTIONED_OPF)
        zf.writestr("OEBPS/nav.xhtml", SECTIONED_NAV)
        zf.writestr("OEBPS/ch1.xhtml", SECTIONED_CHAPTER)
    return Path(path)

# The same shape as the sectioned book, except that its headings carry no `id`
# at all — the publisher's export, and the shape of 自由的窄廊: the contents can
# name a section only by the heading's own text, so every in-chapter entry
# arrives with `anchor: None` and its chapter's own href (PITFALLS 5). The last
# section is deliberately short: its heading cannot be brought up to the reading
# line, which is the case the highlight's reading-line rule alone gets wrong.
UNANCHORED_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Unanchored Book</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:unanchored-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
    <itemref idref="c2"/>
  </spine>
</package>
"""

UNANCHORED_NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <ol>
      <li><a href="ch1.xhtml">Chapter One</a></li>
      <li><a href="ch2.xhtml">Chapter Two</a></li>
    </ol>
  </nav>
</body>
</html>
"""

UNANCHORED_SECTIONS = ("First Section", "Second Section", "Last Section")


def _unanchored_chapter(title: str) -> str:
    """One chapter whose sections are named only by their own headings."""
    parts = [f"  <h1>{title}</h1>"]
    for name in UNANCHORED_SECTIONS:
        parts.append(f"  <h2>{name}</h2>")
        # Enough prose to scroll: the reading line is what the highlight measures
        # against, and a section that fits on one screen would measure nothing.
        count = 1 if name == UNANCHORED_SECTIONS[-1] else 14
        for i in range(count):
            parts.append(
                f"  <p>{name} of {title}, paragraph {i}: a block of prose long "
                "enough to be read rather than skimmed, so that the section runs "
                "past the fold and the reading line has somewhere to be.</p>")
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml">\n'
            f'<head><title>{title}</title></head>\n<body>\n'
            + "\n".join(parts) + "\n</body>\n</html>\n")


def write_unanchored_epub(path) -> Path:
    """A book whose contents names sections that its headings give no id to."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", UNANCHORED_OPF)
        zf.writestr("OEBPS/nav.xhtml", UNANCHORED_NAV)
        zf.writestr("OEBPS/ch1.xhtml", _unanchored_chapter("Chapter One"))
        zf.writestr("OEBPS/ch2.xhtml", _unanchored_chapter("Chapter Two"))
    return Path(path)


# A nav that names only the volumes — the shape a Calibre MOBI->EPUB conversion
# leaves behind: the chapters inside each volume exist only as headings in the
# volume's own document, so the *declared* contents stops at the volume. The
# adapter asks epubx for the derived outline, which fills those chapters in.
VOLUME_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Volume Book</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:volume-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="v1" href="vol1.xhtml" media-type="application/xhtml+xml"/>
    <item id="v2" href="vol2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="v1"/>
    <itemref idref="v2"/>
  </spine>
</package>
"""

VOLUME_NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <ol>
      <li><a href="vol1.xhtml">Volume One</a></li>
      <li><a href="vol2.xhtml">Volume Two</a></li>
    </ol>
  </nav>
</body>
</html>
"""

VOLUME_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{title}</title></head>
<body>
  <h2 id="v">{title}</h2>
  <p>{title} opens with a paragraph long enough that the text detector sees a
     real book and not a page of pictures, and it keeps going well past the
     threshold so the volume is not mistaken for a scan.</p>
  <h3 id="{c1}">Chapter 1</h3>
  <p>The first chapter of {title}, whose heading the nav never names.</p>
  <h3 id="{c2}">Chapter 2</h3>
  <p>The second chapter, also named only by its heading.</p>
</body>
</html>
"""


def write_volume_epub(path) -> Path:
    """A book whose nav names only its volumes, not the chapters inside them."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", VOLUME_OPF)
        zf.writestr("OEBPS/nav.xhtml", VOLUME_NAV)
        zf.writestr("OEBPS/vol1.xhtml", VOLUME_CHAPTER.format(
            title="Volume One", c1="c1", c2="c2"))
        zf.writestr("OEBPS/vol2.xhtml", VOLUME_CHAPTER.format(
            title="Volume Two", c1="c3", c2="c4"))
    return Path(path)




# Real content DRM, modelled on epubx's fixture: an EncryptedKey means a
# licence is in play, and epubx names the book `unsupported` at open.
DRM_ENCRYPTION = """<?xml version="1.0" encoding="UTF-8"?>
<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"
            xmlns:enc="http://www.w3.org/2001/04/xmlenc#">
  <enc:EncryptedKey Id="KEY">
    <enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#rsa-1_5"/>
  </enc:EncryptedKey>
</encryption>
"""

TWIN_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter One</title></head>
<body>
  <p>Another book that happens to share the title of the fixture, with enough
     prose that the detector sees a text book rather than a scan; the words
     keep going well past the threshold, which is the point of them.</p>
</body>
</html>
"""


def write_twin_epub(path) -> Path:
    """A different book with the same title as the fixture — the collision case.

    The identifier differs, which is what decides that a re-upload of this
    book must not replace the first one in place.
    """
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Fixture Book</dc:title>
    <dc:creator>Jane Doe</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:fixture-0002</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/ch1.xhtml", TWIN_CHAPTER)
    return Path(path)


LOCKED_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter One</title></head>
<body>
  <p>A locked book still carries its metadata, so its title and cover reach
     the library; its text, however, is licence-protected and named as such
     rather than being rendered as garbage.</p>
</body>
</html>
"""


def write_drm_epub(path) -> Path:
    """A licence-protected book: epubx names it DRM at open, never raises."""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Locked Book</dc:title>
    <dc:creator>Ann Lock</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:locked-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/ch1.xhtml", LOCKED_CHAPTER)
        zf.writestr("META-INF/encryption.xml", DRM_ENCRYPTION)
    return Path(path)


# A book whose first note runs on for several paragraphs: the note's own
# paragraph carries the id, the paragraphs that continue it carry none, and
# the next note's paragraph follows. epubx resolves a note to the paragraph
# its anchor owns; the adapter must gather the rest up to the next note.
MULTIBLOCK_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Multiblock Notes</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:multiblock-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""

MULTIBLOCK_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Chapter One</title></head>
<body>
  <h1 id="top">Chapter One</h1>
  <p>The body opens with prose that names the first note<a epub:type="noteref" href="#note-1">1</a> and the second<a epub:type="noteref" href="#note-2">2</a>, and keeps going well past the point where the detector would mistake this chapter for a page of pictures.</p>
  <p id="note-1">The first note opens here, and</p>
  <p>it continues into a second paragraph with no id of its own.</p>
  <p id="note-2">The second note stands alone.</p>
</body>
</html>
"""


def write_multiblock_note_epub(path) -> Path:
    """A book whose first note spans several paragraphs."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", MULTIBLOCK_OPF)
        zf.writestr("OEBPS/ch1.xhtml", MULTIBLOCK_CHAPTER)
    return Path(path)


# A book that ships its own JavaScript, in both of the vectors a book has: a
# `<script>` element and an inline handler. The reader serves the book's bytes
# untouched and relies on two guards — the frame's sandbox (no `allow-scripts`)
# and the response's `script-src 'none'` — so the only way to show that a
# book's code never runs is in a browser. Each vector sets its own marker, and
# the test loads this markup with the guard stripped away to show the markers
# are real rather than a fixture that could never have run.
SCRIPTED_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<title>Chapter One</title>
<script>document.documentElement.setAttribute("data-book-script-ran", "1");</script>
</head>
<body onload="document.documentElement.setAttribute('data-book-handler-ran', '1')">
  <h1 id="top">Scripted Book</h1>
  <p>A book that carries its own script, and a reader that must not run it.
     The prose is here because a chapter is a chapter of text; the two markers
     above are what the browser test looks for, and their absence is the guard
     doing its work rather than an accident of the fixture.</p>
</body>
</html>
"""

SCRIPTED_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Scripted Book</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:scripted-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""


def write_scripted_epub(path) -> Path:
    """A book whose only chapter carries a script and an inline handler."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", SCRIPTED_OPF)
        zf.writestr("OEBPS/ch1.xhtml", SCRIPTED_CHAPTER)
    return Path(path)


# A chapter of LaTeX — the shape a math-heavy book ships, and the one the shell
# draws itself. Four formulas (two inline in the dollar spelling, one display in
# the bracket spelling, one beside a macro no renderer knows), three prices that
# must *not* be read as math, and the book's own script, which must still never
# run. Every assertion in `test_browser.py::test_the_shell_draws_a_books_latex`
# counts one of those.
LATEX_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<title>LaTeX</title>
<script>document.documentElement.setAttribute("data-book-script-ran", "1");</script>
</head>
<body>
  <h1 id="top">LaTeX</h1>
  <p>Inline math is $x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$, and it sits in a
     sentence long enough that the chapter is plainly prose rather than a page of
     pictures, which is what the library checks before it will render a book at
     all.</p>
  <p>A display formula is written like this:
     \\[ \\int_0^1 x^2 \\, dx = \\tfrac{1}{3} \\] and the book expects it pulled
     out and centred on a line of its own.</p>
  <p>Prices are written like this: $5 for the paperback, $10 for the hardback,
     and $30 for the set — none of which is mathematics, so none of it may be
     drawn as a formula.</p>
  <p>A macro nobody knows, $\\undefinedmacro{x}$, must not take the sentence
     down with it, and $a^2 + b^2 = c^2$ beside it still draws.</p>
</body>
</html>
"""

LATEX_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>LaTeX Book</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:latex-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="latex.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""


def write_latex_epub(path) -> Path:
    """A book whose formulas are LaTeX — what the shell's math pass is for."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", LATEX_OPF)
        zf.writestr("OEBPS/latex.xhtml", LATEX_CHAPTER)
    return Path(path)


# A book whose first paragraph repeats a sentence: the shape that made
# `block.text.indexOf(selection)` answer "the first one" whatever the reader had
# selected, so a mark made on the second sentence was painted on the first
# (REVIEW P2-10). The middle text is what tells the two occurrences apart, so a
# test can say which one a mark landed on. The paragraph is written on one line
# — one text node — because that is what the wrap splits.
REPEATED_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter One</title></head>
<body>
  <h1 id="top">Chapter One</h1>
  <p>The same sentence twice. In between stands a marker. The same sentence twice.</p>
  <p>A second paragraph follows, so the chapter plainly carries prose and the
     paragraph the reader selected is not the only block in it.</p>
</body>
</html>
"""

REPEATED_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Repeated Sentence</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:repeated-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""


def write_repeated_epub(path) -> Path:
    """A book whose chapter repeats a sentence inside one paragraph."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", REPEATED_OPF)
        zf.writestr("OEBPS/ch1.xhtml", REPEATED_CHAPTER)
    return Path(path)


# A paragraph whose selection begins immediately after an inline element. The
# wrap maps a stored mark back to a Range in the served document, and a range
# that *starts* at the end of an inline element's text node partially selects
# that element — which `Range.surroundContents` refuses, so the mark was stored
# and then never painted (项狄传 vol 5 ch 34, where "Ars longa，——和Vita brevis"
# follows `<small>希波克拉底</small>`).
INLINE_CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Chapter One</title></head>
<body>
  <h1 id="top">Chapter One</h1>
  <p>The physician said <small>Hippocrates</small>Ars longa and then carried on,
     so this paragraph plainly carries real prose rather than a fragment, and the
     sentence runs well past the phrase the reader marked.</p>
  <p>A second paragraph follows, so the paragraph the reader marked is not the
     only block in the chapter.</p>
</body>
</html>
"""

INLINE_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Inline Element</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:inline-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""


def write_inline_epub(path) -> Path:
    """A book whose paragraph splits its prose with an inline element."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", INLINE_OPF)
        zf.writestr("OEBPS/ch1.xhtml", INLINE_CHAPTER)
    return Path(path)


# A chapter long enough to scroll, with paragraphs that name themselves. A
# reading position is anchored to the block at the top of the viewport (REVIEW
# P2-10), and proving that takes more than a screenful: the test scrolls to a
# named paragraph and asks where the anchor landed.
LONG_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Long Book</dc:title>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:long-0001</dc:identifier>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
  </spine>
</package>
"""


def write_long_epub(path, paragraphs: int = 40) -> Path:
    """A book with one chapter of `paragraphs` self-naming paragraphs."""
    body = "\n".join(
        f'  <p id="p{i}">Paragraph {i} of the long fixture is a block of prose '
        f'long enough to be read rather than skimmed, and it names itself so a '
        f'test can say which one is at the top of the screen.</p>'
        for i in range(paragraphs))
    chapter = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>Chapter One</title></head>\n'
        '<body>\n  <h1 id="top">Chapter One</h1>\n'
        f"{body}\n</body>\n</html>\n"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", LONG_OPF)
        zf.writestr("OEBPS/ch1.xhtml", chapter)
    return Path(path)