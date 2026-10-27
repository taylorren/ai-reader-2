"""Build a small EPUB whose whole purpose is to show whether math displays.

The reader serves the book's own XHTML in a sandboxed iframe and injects no
renderer of its own, so "does the formula show?" is a question about the
*format the book ships*, not about the reader's code. That makes a book with
one format per chapter the honest test — and the answer is not the same for
each of the three:

  1. MathML  — EPUB 3's own math. The browser renders it natively, with no
               script, so it displays even inside the script-less sandbox.
               epubx models it too (`kind == "math"`, a `mathml` attribute
               tree) and says of that path: "Math has 0 occurrences across
               the corpus ... empirically unvalidated until a real math EPUB
               appears" (epubx/content.py, `_math_attrs`).
  2. Images  — the EPUB 2 way, and what most publishers still ship. A picture
               is a picture: it displays, and the reader's own click-to-pop-out
               works on it.
  3. `$...$`  — LaTeX source. Nothing draws LaTeX by itself, and the sandbox has
               no `allow-scripts` (templates/reader.html), so a MathJax the book
               ships never runs — SPEC.md used to name that as an open
               trade-off. The reader now closes it from the other side: the
               shell converts the formulas itself (static/vendor/temml, LaTeX →
               MathML) and puts the result in the frame's document, leaving the
               book's file and the book's scripts alone. MathML rather than a
               picture of the formula, so the formula stays text a reader can
               select — and 复制文本 hands them the LaTeX, not the rendering.
               This chapter is where that is tested, including the two shapes
               that must *not* be converted (a price, and a macro the converter
               does not know) and the book's own script, which must still not
               run.

    uv run python scripts/make_math_epub.py            # -> math-formulas.epub
    uv run python scripts/make_math_epub.py -o /tmp/m.epub

Upload the file from the library page (the ＋ card), then read it: chapter 1
should be typeset mathematics, chapter 2 pictures of formulas, and chapter 3
the literal characters `$E = mc^2$`. Toggling 纸张 / 书本 changes how each is
dressed, and 夜间模式 tests the paper sheet's colours against the formulas.

No dependencies beyond the standard library, and no network: the file is built
from string constants in this module, the same way `tests/fixtures.py` builds
its books. Entry timestamps are pinned, so the same input gives the same bytes
and two runs can be compared with `sha256sum`.

**What the first run found, in the library rather than in the reader.** A
paragraph holding inline `<math>` loses the prose that follows the formula, and
the formula's tail is appended to the math block instead — epubx's
`_text_excluding` reads each node's `.text` and never its `.tail`, so

    <p>PROSE-BEFORE <math>…</math> PROSE-AFTER.</p>

parses as paragraph `'PROSE-BEFORE'` plus math `'a+b PROSE-AFTER.'`. The same
function builds its skip set from `id()` of lxml proxies that are dropped
before the second walk — the pitfall epubx documents for `_emitted` — so
membership is unreliable in both directions, and fragments of the formula leak
back into the paragraph: this book's own chapter 1 reports
`'The area of a circle is +b'` for a paragraph whose prose continues well past
its two formulas. Display is unaffected, because the reader serves the book's
own bytes; the extracted text is not, and that text is what a highlight anchors
to and what the AI is given. It belongs upstream in epubx, not in a workaround
here.
"""

from __future__ import annotations

import argparse
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

# EPUB 3, because MathML is an EPUB 3 feature: an EPUB 2 book may not carry it,
# and a reading system that does not know MathML shows the character data
# instead. The title is what the library files the book under (the slug is the
# title verbatim), so it is deliberately URL-safe.
OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Math Formula Test</dc:title>
    <dc:creator>ai-reader-2 test fixture</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="bookid">urn:uuid:ai-reader-2-math-0001</dc:identifier>
    <dc:publisher>ai-reader-2</dc:publisher>
    <dc:date>2026-10-27</dc:date>
    <meta property="dcterms:modified">2026-10-27T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="css" href="style.css" media-type="text/css"/>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
    <item id="c3" href="ch3.xhtml" media-type="application/xhtml+xml" properties="scripted"/>
    <item id="mjs" href="mathjax.js" media-type="text/javascript"/>
    <item id="quadratic" href="img/quadratic.svg" media-type="image/svg+xml"/>
    <item id="euler" href="img/euler.svg" media-type="image/svg+xml"/>
  </manifest>
  <spine>
    <itemref idref="c1"/>
    <itemref idref="c2"/>
    <itemref idref="c3"/>
  </spine>
</package>
"""

# Chapter 1's sections are nested in the contents on purpose: an in-chapter
# anchor is what the reader's TOC highlight measures (reader.js,
# `frameAnchorInView`), and a formula's own id is one of the anchors a book can
# point at.
NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <ol>
      <li><a href="ch1.xhtml">1. MathML — the EPUB 3 way</a>
        <ol>
          <li><a href="ch1.xhtml#display">1.1 A display formula</a></li>
          <li><a href="ch1.xhtml#inline">1.2 Inline, inside a sentence</a></li>
          <li><a href="ch1.xhtml#big">1.3 Big operators</a></li>
        </ol>
      </li>
      <li><a href="ch2.xhtml">2. Formulas as pictures</a></li>
      <li><a href="ch3.xhtml">3. LaTeX source, and a MathJax that must not run</a></li>
    </ol>
  </nav>
</body>
</html>
"""

# The book's own stylesheet. It matters twice: in 书本 mode it is the only
# styling there is (the reader injects nothing), and in 纸张 mode the reader's
# own rules use `!important`, so whatever survives here is what the publisher
# gets to keep. `.formula` centres display math; `img.inline-formula` sets the
# baseline alignment the paper sheet does not touch; `.ran-banner` is only ever
# visible if the sandbox failed (chapter 3).
STYLE = """body { font-family: Georgia, "Noto Serif CJK SC", serif; line-height: 1.75; margin: 1.5em; }
h1 { font-size: 1.4em; }
h2 { font-size: 1.15em; margin-top: 1.6em; }
.formula { text-align: center; margin: 1.1em 0; }
.formula math { font-size: 1.25em; }
.note { font-size: 0.82em; color: #8a7f6a; border-left: 3px solid #d8cdb4; padding-left: 0.7em; }
img.inline-formula { vertical-align: -0.2em; }
figure { margin: 1.2em 0; text-align: center; }
figcaption { font-size: 0.82em; color: #8a7f6a; margin-top: 0.4em; }
.ran-banner { background: #b3261e; color: #ffffff; padding: 0.6em; font-weight: bold; }
"""


# ---- Chapter 1: MathML ----------------------------------------------------
#
# Every `<math>` carries its own `xmlns`: the document is XHTML, so the MathML
# namespace is not implied there (it is implied when the same bytes are parsed
# as HTML, which is what the reader serves them as — `content_type` maps
# `application/xhtml+xml` to `text/html`). `display="block"` is what asks for a
# centred display formula rather than inline math; the wrapping `.formula` div
# is the book's own styling for it.

CHAPTER_1 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head><title>1. MathML</title><link rel="stylesheet" href="style.css"/></head>
<body>
  <h1 id="ch1">1. MathML — the EPUB 3 way</h1>
  <p>This chapter is written in MathML, the math format EPUB 3 defines and the
     only one a browser renders with no script at all: the engine has native
     MathML support, so a book that ships it shows typeset mathematics even
     inside the reader's sandboxed, script-less frame. Everything below should
     appear as mathematics — stacked fractions, radicals, raised superscripts —
     and not as markup, and not as a string of letters and digits. The prose
     around each formula is here because a chapter of formulas and pictures
     alone is what the library calls an image-only book, and it would refuse to
     render the whole thing.</p>

  <h2 id="display">1.1 A display formula, in its own block</h2>
  <div class="formula">
    <math xmlns="http://www.w3.org/1998/Math/MathML" display="block">
      <mrow>
        <mi>x</mi><mo>=</mo>
        <mfrac>
          <mrow><mo>−</mo><mi>b</mi><mo>±</mo>
            <msqrt><mrow><msup><mi>b</mi><mn>2</mn></msup><mo>−</mo><mn>4</mn><mi>a</mi><mi>c</mi></mrow></msqrt>
          </mrow>
          <mrow><mn>2</mn><mi>a</mi></mrow>
        </mfrac>
      </mrow>
    </math>
  </div>
  <p class="note">Expected: the quadratic formula, with the root drawn as a
     radical over b²−4ac, and a real fraction bar rather than a slash. This is
     the same formula chapter 3 shows as LaTeX source.</p>

  <h2 id="inline">1.2 Inline, inside a sentence</h2>
  <p>The area of a circle is
     <math xmlns="http://www.w3.org/1998/Math/MathML"><mrow><mi>π</mi><msup><mi>r</mi><mn>2</mn></msup></mrow></math>,
     which has been known for a very long time, and this sentence carries prose
     on both sides of the formula so a reader can select the words around it —
     that selection is what becomes a highlight. A second, smaller formula sits
     here too,
     <math xmlns="http://www.w3.org/1998/Math/MathML"><mrow><mi>a</mi><mo>+</mo><mi>b</mi><mo>=</mo><mi>b</mi><mo>+</mo><mi>a</mi></mrow></math>,
     so the inline case is seen twice: once in the middle of a clause and once
     beside a dash.</p>
  <p class="note">Expected: πr² typeset inside the sentence, on the same line,
     with the 2 raised and not spelled out. Selecting this sentence copies the
     formula's character data — πr2 — and never a run of XML.</p>

  <h2 id="big">1.3 Big operators, roots, fences, a system</h2>
  <div class="formula">
    <math xmlns="http://www.w3.org/1998/Math/MathML" display="block">
      <mrow>
        <munderover><mo>∑</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mi>n</mi></munderover>
        <msup><mi>i</mi><mn>2</mn></msup><mo>=</mo>
        <mfrac><mrow><mi>n</mi><mo>(</mo><mi>n</mi><mo>+</mo><mn>1</mn><mo>)</mo><mo>(</mo><mn>2</mn><mi>n</mi><mo>+</mo><mn>1</mn><mo>)</mo></mrow><mn>6</mn></mfrac>
      </mrow>
    </math>
  </div>
  <div class="formula">
    <math xmlns="http://www.w3.org/1998/Math/MathML" display="block">
      <mrow>
        <mroot><mi>x</mi><mn>3</mn></mroot><mo>+</mo>
        <mfenced open="(" close=")"><mrow><mi>y</mi><mo>−</mo><mn>1</mn></mrow></mfenced><mo>+</mo>
        <mfrac><mn>1</mn><mn>2</mn></mfrac><mo>=</mo><mn>0</mn>
      </mrow>
    </math>
  </div>
  <div class="formula">
    <math xmlns="http://www.w3.org/1998/Math/MathML" display="block">
      <mtable columnalign="right left" columnspacing="0.6em">
        <mtr><mtd><mn>2</mn><mi>x</mi><mo>+</mo><mi>y</mi></mtd><mtd><mo>=</mo><mn>7</mn></mtd></mtr>
        <mtr><mtd><mi>x</mi><mo>−</mo><mi>y</mi></mtd><mtd><mo>=</mo><mn>2</mn></mtd></mtr>
      </mtable>
    </math>
  </div>
  <p class="note">Expected: a summation whose limits sit above and below the ∑,
     a cube root with the 3 in its notch, parentheses that stretch around what
     they hold, and a two-row system whose equals signs line up.</p>

  <h2 id="ids">1.4 A formula with an id, and one in Chinese</h2>
  <p>A book can hang an id on a formula and link to it, exactly as it links to a
     heading. The next one is <code>eq-quadratic</code>, and chapter 3 links
     back to it: a click on that link should land here, with the formula still
     typeset and the chapter's place in the contents unchanged.</p>
  <div class="formula">
    <math xmlns="http://www.w3.org/1998/Math/MathML" display="block" id="eq-quadratic">
      <mrow>
        <mi>x</mi><mo>=</mo>
        <mfrac>
          <mrow><mo>−</mo><mi>b</mi><mo>±</mo>
            <msqrt><mrow><msup><mi>b</mi><mn>2</mn></msup><mo>−</mo><mn>4</mn><mi>a</mi><mi>c</mi></mrow></msqrt>
          </mrow>
          <mrow><mn>2</mn><mi>a</mi></mrow>
        </mfrac>
      </mrow>
    </math>
  </div>
  <p>Math is not only Latin. The circumference of a circle in Chinese,
     <math xmlns="http://www.w3.org/1998/Math/MathML"><mrow><mtext>周长</mtext><mo>=</mo><mn>2</mn><mi>π</mi><mi>r</mi></mrow></math>,
     needs a CJK font inside the math font stack — the Latin letters and the
     Chinese come from different fonts, and a machine with only one of them
     shows boxes or fallback glyphs for the other. Those fonts are the
     browser's, not the server's, so it is the reader's own machine that has
     to carry both.</p>

  <h2 id="tex">1.5 The same formula, with its LaTeX kept alongside</h2>
  <p>Books converted from LaTeX usually ship the MathML and the source it came
     from, in an <code>annotation</code> element the reader never sees. It is
     still text in the document, which is worth knowing: the library's own text
     extraction carries the annotation into the chapter's prose, so the AI is
     given the TeX as well as the formula.</p>
  <div class="formula">
    <math xmlns="http://www.w3.org/1998/Math/MathML" display="block">
      <semantics>
        <mrow><msup><mi>e</mi><mrow><mi>i</mi><mi>π</mi></mrow></msup><mo>+</mo><mn>1</mn><mo>=</mo><mn>0</mn></mrow>
        <annotation encoding="application/x-tex">e^{i\\pi} + 1 = 0</annotation>
      </semantics>
    </math>
  </div>
  <p class="note">Expected: Euler's identity, typeset — e with a raised iπ, then
     + 1 = 0. The TeX source in the annotation must not be visible on the page.</p>
</body>
</html>
"""

# ---- Chapter 2: formulas as pictures --------------------------------------
#
# The EPUB 2 answer, and still what most publishers ship. Nothing has to
# understand a picture, so it displays anywhere — the costs are the ones a
# picture always has: it does not follow the reader's font size, it cannot be
# selected or searched, and the only text it contributes is its `alt`.

CHAPTER_2 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head><title>2. Formulas as pictures</title><link rel="stylesheet" href="style.css"/></head>
<body>
  <h1 id="ch2">2. Formulas as pictures</h1>
  <p>A formula can simply be a picture. That is the EPUB 2 answer and still the
     most common one, because nothing downstream has to understand anything: the
     file is served, the browser paints it, and the formula looks the way the
     publisher's typesetter drew it. The costs are the ones a picture always
     has — it does not follow the reader's font size, it cannot be selected or
     searched, and the only words it contributes to the text are its alt
     attribute. Three shapes of picture are worth seeing side by side, because
     the reader treats them differently.</p>

  <h2 id="figure">2.1 A formula as a figure</h2>
  <figure>
    <img src="img/quadratic.svg" alt="The quadratic formula: x equals minus b plus or minus the square root of b squared minus four a c, all over two a"
         width="240" height="86"/>
    <figcaption>The quadratic formula as an SVG file referenced by an
      &lt;img&gt;. Click it: the reader pops it out at its own size, which is
      the only way to read a formula the reading column has scaled down.</figcaption>
  </figure>
  <p class="note">Expected: a picture of the formula — a fraction bar with the
     root above it. It does not reflow when you press A+ or A−: only the text
     around it changes size. In 纸张 mode the paper sheet's own rule
     (<code>max-width: 100%</code>, <code>height: auto</code>) keeps it inside
     the column without distorting it.</p>

  <h2 id="inline">2.2 A formula inline in a sentence</h2>
  <p>An inline picture sits on the text baseline, so its height has to be small
     enough not to push the lines apart: Euler's identity,
     <img src="img/euler.svg" class="inline-formula" width="100" height="30"
          alt="e to the power of i pi, plus one, equals zero"/>,
     is short enough to be drawn at the size of the surrounding text. A taller
     one would look like a dropped cap or a hole in the paragraph, which is the
     usual way a picture-based book looks wrong.</p>
  <p class="note">Expected: the formula appears inline, vertically aligned with
     the sentence — the book's own <code>vertical-align</code> rule survives in
     both 纸张 and 书本 mode, because the paper sheet does not override it.</p>

  <h2 id="svg">2.3 An SVG drawn in the document</h2>
  <p>The third shape is a picture that is not a file: vector markup written
     straight into the chapter. The reader has nothing to resolve and nothing to
     serve, so it displays as long as the browser understands SVG — and the
     book's text extraction still sees the labels inside it.</p>
  <div class="formula">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 46" width="200" height="46" role="img">
      <title>f of x equals x squared plus two x plus one</title>
      <text x="6" y="32" font-family="Georgia, 'Times New Roman', serif" font-size="20" fill="#333"><tspan font-style="italic">f</tspan>(<tspan font-style="italic">x</tspan>) = <tspan font-style="italic">x</tspan><tspan dy="-9" font-size="13">2</tspan><tspan dy="9"> + 2</tspan><tspan font-style="italic">x</tspan> + 1</text>
    </svg>
  </div>
  <p class="note">Expected: the same formula, drawn by the document itself. In
     书本 mode the book's own stylesheet styles it; in 纸张 mode the paper sheet
     only caps its width.</p>
</body>
</html>
"""

QUADRATIC_SVG = """<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 86" width="240" height="86" role="img">
  <title>The quadratic formula</title>
  <g font-family="Georgia, 'Times New Roman', serif" fill="#333333">
    <text x="8" y="54" font-size="24" font-style="italic">x</text>
    <text x="26" y="54" font-size="24">=</text>
    <line x1="66" y1="42" x2="232" y2="42" stroke="#333333" stroke-width="1.4"/>
    <text x="68" y="34" font-size="20" font-style="italic">−b ± √(b² − 4ac)</text>
    <text x="140" y="66" font-size="20" font-style="italic">2a</text>
  </g>
</svg>
"""

EULER_SVG = """<?xml version="1.0" encoding="utf-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 30" width="100" height="30" role="img">
  <title>Euler's identity</title>
  <text x="3" y="22" font-family="Georgia, 'Times New Roman', serif" font-size="18" fill="#333333"><tspan font-style="italic">e</tspan><tspan dy="-8" font-size="12" font-style="italic">iπ</tspan><tspan dy="8"> + 1 = 0</tspan></text>
</svg>
"""


# ---- Chapter 3: LaTeX source, and the script that must not run ------------
#
# The chapter this whole book exists for. `$...$` is not math to a browser: it
# is four characters and some text between them. Something has to typeset it,
# and in this reader nothing does — the frame is sandboxed without
# `allow-scripts`, so a book's bundled MathJax never executes (SPEC.md names
# this as an open trade-off, not a solved case). The stand-in script below
# makes the *sandbox* testable: if it ever runs, it paints a red banner and
# sets `data-mathjax-ran`, so the failure is visible rather than silent.
#
# Every backslash is doubled: this is a normal string, and `\f` in `\frac` is a
# form feed, `\t` in `\tfrac` a tab. The served chapter must carry one backslash.

CHAPTER_3 = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head>
  <title>3. LaTeX source</title>
  <link rel="stylesheet" href="style.css"/>
  <script src="mathjax.js"></script>
</head>
<body>
  <h1 id="ch3">3. LaTeX source, and a MathJax that must not run</h1>
  <p>This chapter is what a math-heavy EPUB usually contains in the wild: the
     formulas written as LaTeX between dollar signs, and a copy of MathJax the
     book expects to be allowed to run so that it can typeset them. The reader
     converts these formulas itself — the frame it serves this chapter in is
     marked <code>sandbox="allow-same-origin"</code>, with no
     <code>allow-scripts</code>, so the script tag in this chapter's head never
     executes; instead the shell converts the LaTeX to MathML and puts that in
     the page. The book's file is never rewritten, and nothing of the book's own
     ever runs. This is what the trade-off named at the end of SPEC.md looks like
     from the reader's side: the sandbox stays shut, and the formula still
     arrives — as text, so it can be selected, searched, and copied.</p>

  <h2 id="source">3.1 The same formula, as source</h2>
  <p>Here is the quadratic formula from chapter 1, exactly as such a publisher
     wrote it. Inline math is $x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$, and the
     other two spellings are common as well: \\(a^2 + b^2 = c^2\\) for inline, and
     a display formula written like this in a paragraph of its own —
     \\[ \\int_0^1 x^2 \\, dx = \\tfrac{1}{3} \\] — which the book expects to be
     pulled out and centred.</p>
  <p class="note">Expected: three typeset formulas — one inline, one inline in
     the bracket spelling, one display formula centred on its own line. Select
     one: it is text, not a picture, so the selection can be copied — and
     复制文本 hands you the LaTeX the book wrote rather than the characters the
     browser drew. If you see dollar signs and backslashes here, the reader's
     converter did not run: everything else in the book still reads normally
     when it does not.</p>

  <h2 id="hazards">3.2 What must not be read as math</h2>
  <p>Two shapes have to come through the pass untouched. Prices are written like
     this: $5 for the paperback, $10 for the hardback, and $30 for the set — and
     none of those three is mathematics, so none of them may be drawn. Neither
     may a macro this build has never heard of: $\\undefinedmacro{x}$ has to fail
     on its own, without taking the rest of the sentence with it, while
     $a^2 + b^2 = c^2$ in the very same paragraph still draws.</p>
  <p class="note">Expected: the three prices stay exactly as written, and the
     macro the converter does not know keeps the book's own source where the
     formula was — in place, with the sentence around it intact and the second
     formula in the same paragraph still converted. A blank gap, a swallowed
     sentence, or a price turned into a formula would each mean the pass is
     guessing.</p>

  <h2 id="probe">3.3 The script that must not run</h2>
  <p>This chapter loads a stand-in MathJax from its own manifest, and it also
     carries a small inline script that paints a red banner at the top of the
     page. If the reader's sandbox is doing its job, neither has run: there is no
     banner, and the frame's document element carries no
     <code>data-mathjax-ran</code> attribute. To check it for yourself, open this
     chapter and run this in the browser's console:</p>
  <pre>document.querySelector('#chapter-frame').contentDocument.documentElement.dataset</pre>
  <p class="note">Expected: <code>DOMStringMap {}</code> — empty. A red banner
     reading "mathjax.js RAN" would mean the book's scripts are executing, which
     is a security bug rather than a math bug, and it is the one thing this
     chapter is here to catch.</p>

  <h2 id="link">3.4 A link to a formula in another chapter</h2>
  <p>The book's own links still work natively, which is the reason this
     rendering model was chosen: <a href="ch1.xhtml#eq-quadratic">the same
     formula, typeset</a> in chapter 1 is one click away, and its target is a
     <code>&lt;math&gt;</code> element carrying an id rather than a heading.</p>
  <p class="note">Expected: the click loads chapter 1 and lands on the formula.
     The contents drawer keeps highlighting the chapter entry — a formula is not
     a heading, so there is no section for the highlight to move to.</p>

  <script>
    (function () {
      document.documentElement.setAttribute("data-mathjax-ran", "1");
      var banner = document.createElement("p");
      banner.className = "ran-banner";
      banner.textContent = "⚠ mathjax.js RAN — the book's scripts are executing.";
      document.body.insertBefore(banner, document.body.firstChild);
    })();
  </script>
</body>
</html>
"""

# A stand-in for a book's bundled MathJax: the naive renderer a publisher would
# ship, reduced to what is needed to make the sandbox visible. A raw string, so
# the backslashes in the regex reach the file as written.
MATHJAX_JS = r"""/* Stand-in for a bundled MathJax (math test book, chapter 3).
   A real book ships the whole library here; this one only has to be
   recognisable. If it ever runs, the reader's sandbox has been relaxed: it
   stamps the document and paints the red banner. */
(function () {
  document.documentElement.setAttribute("data-mathjax-ran", "1");
  var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  var nodes = [], node;
  while ((node = walker.nextNode())) nodes.push(node);
  nodes.forEach(function (text) {
    if (!/\$[^$]+\$/.test(text.nodeValue)) return;
    var span = document.createElement("span");
    span.className = "mjx";
    span.style.background = "#fff4b8";
    span.textContent = text.nodeValue.replace(/\$([^$]+)\$/g, "\u27e8$1\u27e9");
    text.parentNode.replaceChild(span, text);
  });
  var banner = document.createElement("p");
  banner.className = "ran-banner";
  banner.textContent = "⚠ mathjax.js RAN — the book's scripts are executing.";
  document.body.insertBefore(banner, document.body.firstChild);
})();
"""


# The archive's contents, in the order they are written. `mimetype` is not
# here: it goes in first and uncompressed, per the OCF spec.
FILES = {
    "META-INF/container.xml": CONTAINER,
    "OEBPS/content.opf": OPF,
    "OEBPS/nav.xhtml": NAV,
    "OEBPS/style.css": STYLE,
    "OEBPS/ch1.xhtml": CHAPTER_1,
    "OEBPS/ch2.xhtml": CHAPTER_2,
    "OEBPS/ch3.xhtml": CHAPTER_3,
    "OEBPS/mathjax.js": MATHJAX_JS,
    "OEBPS/img/quadratic.svg": QUADRATIC_SVG,
    "OEBPS/img/euler.svg": EULER_SVG,
}

# One fixed timestamp for every entry. A zip records each member's mtime, so a
# book built twice would otherwise differ byte for byte — and the docstring
# above promises it does not. 1980-01-01 is the earliest a zip can express, and
# what the `mimetype` member already carries in `tests/fixtures.py`.
EPOCH = (1980, 1, 1, 0, 0, 0)


def write_math_epub(path) -> Path:
    """Write the math test book to `path` and return it.

    `mimetype` goes in first and uncompressed, per the OCF spec — the one
    detail a reading system checks before it will look at anything else.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype", date_time=EPOCH),
                    "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, text in FILES.items():
            info = zipfile.ZipInfo(name, date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, text)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--output", default="math-formulas.epub",
                        help="where to write the book (default: %(default)s)")
    args = parser.parse_args()

    path = write_math_epub(args.output)
    print(f"✓ {path}  ({path.stat().st_size} bytes)")
    print("  ch1  MathML           — should be typeset")
    print("  ch2  SVG pictures     — should display, and pop out on a click")
    print("  ch3  LaTeX           — converted to MathML; no red banner")
    print("  upload it from the library page (the ＋ card)")


if __name__ == "__main__":
    main()

