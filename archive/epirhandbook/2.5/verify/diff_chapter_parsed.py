#!/usr/bin/env python3
# Parser-based page comparison. Same job as diff_chapter.py, without its
# tag-stripping bug.
#
# WHY THIS EXISTS
# diff_chapter.py removes markup with the regex <[^>]+>. That regex assumes a
# '>' inside a tag always ends the tag. It does not: gt/gtsummary builds a table
# id attribute from a bold column header, and in a standalone (non-book) render
# quarto leaves it UNescaped:
#
#   <th id="<strong>Characteristic</strong>" class="gt_col_heading ...">
#
# The regex matches only up to the '>' of the embedded <strong>, so the rest of
# the tag leaks into the extracted "text" and the diff reports a large spurious
# deviation. The book render escapes the same attribute (&lt;strong&gt;), so
# only one side leaks -- which is why the effect looks like a content change.
#
# Measured effect on Phase 3 (individual chapter render vs the Phase 2 book
# render of the same chapter, same image, same content):
#
#   chapter              diff_chapter.py   this script   differing hunks
#   stat_tests               0.9740          0.9987       1 (navbar only)
#   regression               0.9863          0.9993       1 (navbar only)
#   transmission_chains      0.9897          0.9896       many (genuinely volatile)
#
# The bias is always PESSIMISTIC -- it understates similarity, so it can never
# turn a real difference into a false pass. The Phase 1/2 numbers frozen in
# verify/manifest.tsv are therefore still safe as a regression bar; they simply
# understate fidelity on the four gt-table chapters (stat_tests, regression,
# tables_descriptive, survey_analysis).
#
# Usage: diff_chapter_parsed.py <rendered.html> <reference.html> [label]
import sys, re, difflib
from html.parser import HTMLParser


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def words(path):
    p = Text()
    p.feed(open(path, encoding="utf-8", errors="replace").read())
    s = " ".join(p.out)
    s = re.sub(r"\d{4}-\d{2}-\d{2}", "DATE", s)      # same date normalization
    s = re.sub(r"\s+", " ", s).strip()
    return s.split(" ")


rendered, ref = sys.argv[1], sys.argv[2]
label = sys.argv[3] if len(sys.argv) > 3 else ""
a, b = words(rendered), words(ref)
sm = difflib.SequenceMatcher(None, a, b)
hunks = [op for op in sm.get_opcodes() if op[0] != "equal"]
print(f"{label:22} similarity={sm.ratio():.4f}  words rendered={len(a):6} ref={len(b):6}  hunks={len(hunks)}")

for tag, i1, i2, j1, j2 in hunks[:12]:
    print(f"  [{tag}]")
    if i2 > i1:
        print("     rendered:", " ".join(a[i1:i2])[:300])
    if j2 > j1:
        print("     book ref:", " ".join(b[j1:j2])[:300])
if len(hunks) > 12:
    print(f"  ... {len(hunks) - 12} further hunks suppressed")
