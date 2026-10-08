"""Synthetic EPUB fixtures for ai-reader-2.

The same approach as epubx's tests/fixtures.py: tiny books built in tmp
directories, so the suite runs in CI with no real books present. Real-book
behaviour is exercised by test_corpus.py, which skips when EPUBX_CORPUS is
unset.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

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


def write_epub(path) -> Path:
    """A two-chapter book with footnotes, an image, CSS, a cover and a nav TOC."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype must be first and stored, per the OCF spec.
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("OEBPS/content.opf", OPF)
        zf.writestr("OEBPS/nav.xhtml", NAV)
        zf.writestr("OEBPS/style.css", "body { margin: 0; }")
        zf.writestr("OEBPS/ch1.xhtml", CHAPTER_1)
        zf.writestr("OEBPS/ch2.xhtml", CHAPTER_2)
        zf.writestr("OEBPS/img/cover.jpg", JPEG)
        zf.writestr("OEBPS/img/plate one.png", PNG)
    return Path(path)


def write_counting_epub(path) -> Path:
    """A one-chapter book whose text is exactly 'Hello world 汉字'."""
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
        zf.writestr("OEBPS/c.xhtml", COUNTING_CHAPTER)
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