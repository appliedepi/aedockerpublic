#!/usr/bin/env python3
# Phase 3 inline-widget comparison (round-2 remediation, Task 3).
#
# WHY THIS EXISTS
# compare_chapters.py's metric (diff_chapter.py) strips <script>/<style>
# before scoring page TEXT. compare_assets.py only walks each chapter's
# on-disk <chapter>_files/ directory. Neither ever looks at an htmlwidget's
# (DT, plotly, leaflet, ...) JSON payload, because in this handbook that
# payload is embedded INLINE in the chapter's own .html -- it is never
# written to _files/ as a separate file. So a genuine change inside a
# widget's data (e.g. a stochastically-simulated table of forecast counts)
# would be invisible to both existing checks. This script is the third leg.
#
# MECHANISM
# htmlwidgets (the R package underlying DT/plotly/leaflet/... in quarto/
# rmarkdown HTML output) embeds each widget's data as:
#   <script type="application/json" data-for="htmlwidget-XXXXXXXXXXXXXXXXXXXX">
#     { ... the widget's actual configuration/data ... }
#   </script>
# where XXXX...  is a random 20-hex-digit id, freshly generated every
# render, used only to wire the payload to its sibling <div id="htmlwidget-
# XXXX">. It is NOT derived from content and carries no information -- see
# "Independent verification" / README.md, which already established this
# same random-id mechanism from the page-TEXT side (it only ever showed up
# there when it leaked into a gt id attribute or a DT/plotly div's own
# id="..." -- this script goes straight at the JSON payload itself).
#
# NORMALIZATION -- stated explicitly, because over-normalizing here would
# hide exactly what this check exists to find. TWO things are normalized,
# both random per-render identifiers with no content meaning, and NOTHING
# else (no date normalization, no whitespace collapsing beyond what the two
# payloads already have, no numeric rounding):
#
#   1. The literal random htmlwidget-XXXX token, wherever it appears inside
#      a payload's own text (checked empirically: it does NOT actually recur
#      inside the payload body for DT -- only in the data-for attribute and
#      the sibling div's id -- but the substitution is applied
#      unconditionally in case some widget type does embed it).
#
#   2. plotly's OWN internal "cur_data" key -- found only after running this
#      script against the real data and manually tracing every remaining
#      difference in `interactive_plots` and `diagrams` (both plotly
#      widgets): plotly's R package generates a second random hex id per
#      widget, independent of the htmlwidget-XXXX DOM id, used purely as an
#      internal crosstalk bookkeeping key (it appears as the value of
#      "cur_data" and recurs as a dict key inside "visdat"/"attrs" in the
#      same payload). It has nothing to do with htmlwidgets' DOM-id
#      mechanism and was NOT anticipated before running this script for
#      real -- it would have been reported as 5 "genuine" mismatches
#      (interactive_plots x4, diagrams x1) without this. VERIFIED, not
#      assumed: normalizing ONLY this token (found via "cur_data", then its
#      literal occurrences replaced) made all 5 of those payloads
#      byte-identical to their book-reference counterpart, with zero other
#      differences -- confirmed by direct before/after diffing, not merely
#      inferred from the key's name. Because the substitution targets one
#      specific, extracted hex token (not a blanket regex over any
#      hex-looking string), it cannot mask an unrelated real difference
#      sitting elsewhere in the same payload.
#
#   A payload containing a REAL data difference (a different projected case
#   count, a different simulated column) is expected to still show up as a
#   mismatch after both normalizations, and did in practice: epidemic_models
#   widget 1 (the projection results DT table) still differs after both
#   normalizations -- consistent with, and independent corroborating
#   evidence for, README.md's Task 1 finding of unseeded run-to-run
#   randomness in that chapter's forecast.
#
# MATCHING
# Widgets are paired by POSITION (the Nth <script type="application/json"
# data-for="htmlwidget-...."> tag in document order on the render side vs.
# the Nth on the ref side) -- ids cannot be used to pair them, since they are
# random on both sides by construction. This is the same principle already
# used elsewhere in Phase 3: figures are paired by filename (chunk label +
# index), which is deterministic given the same source and the same chunk
# execution order. If the two sides have a different NUMBER of widgets for a
# chapter, that is reported directly as a count mismatch, not silently
# truncated to the shorter list.
#
# ROUND 3 REMEDIATION (third adversarial review): everything above this line
# describes the comparison; through round 2, the script computed all of it
# and then exited 0 unconditionally -- a widget payload regression was
# recorded in the tsv and printed to stdout, but never failed the run. It now
# fails loud, matching compare_chapters.py / compare_assets.py, on four
# conditions: (1) a page missing on either side (was previously just a note,
# now a hard error -- a chapter whose widgets literally could not be checked
# is not a pass); (2) total widget-payload-pairs-compared != the expected
# count established for this dataset (a structural sentinel: catches a
# chapter losing or gaining a whole widget, which the per-payload checks
# below would not otherwise assert); (3) any chapter's widget COUNT differing
# render vs. ref (see MATCHING above) -- always fatal, never allowlisted,
# since a genuinely differing count is a structural change, not a content
# value changing; (4) any payload mismatch NOT on the explicit ALLOWLIST
# below. Applying the lesson from compare_assets.py's round-3 fix: ALLOWLIST
# here is keyed by the EXACT (chapter, widget_index) of each of the 13
# mismatches actually observed in widgets.tsv, not by chapter alone -- a
# chapter-level allowlist would wave through a newly-corrupted OTHER widget
# in the same chapter exactly like compare_assets.py's chapter-level version
# did for figures.
#
# Usage: python3 compare_widgets.py <render_dir> <ref_dir> <out_tsv>
import sys
import os
import re
import glob
import hashlib

WIDGET_RE = re.compile(
    r'<script type="application/json" data-for="(htmlwidget-[0-9a-f]+)">(.*?)</script>',
    re.S,
)

# Total widget-payload PAIRS (rows with an actual render+ref widget on both
# sides -- excludes the "page missing" and "no widgets on either side" rows,
# which are never counted here) established for this dataset: 175, per
# README.md "Inline widget payloads vs. book". A run producing a different
# total means some chapter gained or lost a whole widget -- a structural
# change the per-payload checks below cannot see on their own, since they
# only ever compare pairs that already exist on both sides.
EXPECTED_WIDGET_PAIRS = 175

# Widget payload mismatches documented in README.md as legitimately varying
# run-to-run. Keyed by the EXACT (chapter, widget_index) of each of the 13
# mismatches observed in widgets.tsv -- widget_index is stable and
# deterministic run-to-run because widgets within a chapter are emitted in a
# fixed document order by the same source code every render (the same
# principle that makes filename-pairing valid for figures in
# compare_assets.py); only a payload's CONTENT is expected to vary, never
# its position. Nothing else is tolerated implicitly, including a new
# mismatch at a different widget_index inside one of these same chapters.
# NOTE: transmission_chains has 10 mismatching widget_index values in
# widgets.tsv (0, 2-10 inclusive; only widget_index 1 matches), so the totals
# reconcile as 13 = 2 + 1 + 10. README.md briefly said "9 payloads" here,
# which made its own breakdown sum to 12 against a stated total of 13; the
# prose has since been corrected to 10. widgets.tsv -- this script's own
# committed, reproducible output -- is the ground truth for this allowlist.
ALLOWLIST = {
    ("directories", 0): "README.md 'Inline widget payloads vs. book': widget "
                        "content includes the render's own working-directory "
                        "path (/book vs. quarto's /tmp/Rtmp.../file... for the "
                        "book build) and file modification timestamps, both "
                        "expected to differ run to run by design",
    ("directories", 1): "README.md 'Inline widget payloads vs. book': widget "
                        "content includes the render's own working-directory "
                        "path (/book vs. quarto's /tmp/Rtmp.../file... for the "
                        "book build) and file modification timestamps, both "
                        "expected to differ run to run by design",
    ("epidemic_models", 1): "README.md 'Inline widget payloads vs. book': the "
                        "projection-results DT table; simulated case counts "
                        "differ -- independent corroborating evidence (a "
                        "different code path than the figures) for the same "
                        "unseeded rgamma()/project() finding confirmed "
                        "directly in README.md 'Task 1'",
    ("transmission_chains", 0): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
    ("transmission_chains", 2): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
    ("transmission_chains", 3): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
    ("transmission_chains", 4): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
    ("transmission_chains", 5): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
    ("transmission_chains", 6): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
    ("transmission_chains", 7): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
    ("transmission_chains", 8): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
    ("transmission_chains", 9): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
    ("transmission_chains", 10): "README.md 'Inline widget payloads vs. book': "
                        "already-documented stochastic contact-network "
                        "simulation (no fixed seed); same volatility as this "
                        "chapter's page text (case-ID hashes, "
                        "Nosocomial/Community counts)",
}


def extract_widgets(html_path):
    """Return a list of (widget_id, raw_payload) in document order."""
    try:
        with open(html_path, encoding="utf-8", errors="replace") as f:
            html = f.read()
    except OSError:
        return None
    return [(m.group(1), m.group(2)) for m in WIDGET_RE.finditer(html)]


CUR_DATA_RE = re.compile(r'"cur_data":"([0-9a-f]+)"')


def normalize(widget_id, payload):
    # 1. The widget's own random htmlwidget DOM id, wherever it recurs.
    out = payload.replace(widget_id, "WIDGET_ID")
    # 2. plotly's separate internal "cur_data" crosstalk key (see module
    #    docstring) -- replace its literal value everywhere it recurs
    #    (as the "cur_data" value itself and as a dict key elsewhere in the
    #    same payload, e.g. under "visdat"/"attrs"). Extracted per-payload,
    #    not a fixed pattern, so this only ever touches the exact token that
    #    payload itself generated.
    m = CUR_DATA_RE.search(out)
    if m:
        out = out.replace(m.group(1), "CUR_DATA_ID")
    return out


def sha16(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def page_path(base_dir, chapter, is_render_side):
    if chapter == "index":
        return os.path.join(base_dir, "html_outputs", "index.html") if is_render_side \
            else os.path.join(base_dir, "index.html")
    if is_render_side:
        return os.path.join(base_dir, "html_outputs", "new_pages", f"{chapter}.html")
    return os.path.join(base_dir, "new_pages", f"{chapter}.html")


def main():
    render_dir, ref_dir, out_tsv = sys.argv[1:4]

    book_html = sorted(glob.glob(os.path.join(ref_dir, "new_pages", "*.html")))
    chapters = [os.path.splitext(os.path.basename(p))[0] for p in book_html] + ["index"]

    rows = []
    count_mismatches = []
    genuine_diffs = []
    unexplained = []
    page_missing = []

    for chapter in chapters:
        rp = page_path(render_dir, chapter, is_render_side=True)
        bp = page_path(ref_dir, chapter, is_render_side=False)

        r_widgets = extract_widgets(rp)
        b_widgets = extract_widgets(bp)

        if r_widgets is None or b_widgets is None:
            missing_note = f"page missing: render={rp if r_widgets is None else 'OK'} ref={bp if b_widgets is None else 'OK'}"
            page_missing.append((chapter, missing_note))
            rows.append({
                "chapter": chapter, "widget_index": "NA",
                "render_widget_id": "NA", "ref_widget_id": "NA",
                "payload_bytes_render": "NA", "payload_bytes_ref": "NA",
                "match": "NA",
                "note": missing_note,
            })
            continue

        n_r, n_b = len(r_widgets), len(b_widgets)
        if n_r != n_b:
            count_mismatches.append(chapter)

        n_pairs = min(n_r, n_b)
        if n_pairs == 0 and n_r == n_b == 0:
            rows.append({
                "chapter": chapter, "widget_index": "NA",
                "render_widget_id": "", "ref_widget_id": "",
                "payload_bytes_render": 0, "payload_bytes_ref": 0,
                "match": "NA", "note": "no widgets on either side (valid, expected for text/figure-only chapters)",
            })

        for i in range(n_pairs):
            r_id, r_payload = r_widgets[i]
            b_id, b_payload = b_widgets[i]
            r_norm = normalize(r_id, r_payload)
            b_norm = normalize(b_id, b_payload)
            is_match = (r_norm == b_norm)
            note = ""
            if not is_match:
                note = (f"payload differs after id-normalization "
                        f"(render sha16={sha16(r_norm)}, ref sha16={sha16(b_norm)})")
                genuine_diffs.append((chapter, i))
                allow_reason = ALLOWLIST.get((chapter, i))
                if allow_reason:
                    note += f"; allowlisted -- {allow_reason}"
                else:
                    note += "; UNEXPLAINED -- not on allowlist"
                    unexplained.append((chapter, i))
            rows.append({
                "chapter": chapter, "widget_index": i,
                "render_widget_id": r_id, "ref_widget_id": b_id,
                "payload_bytes_render": len(r_payload), "payload_bytes_ref": len(b_payload),
                "match": "yes" if is_match else "no",
                "note": note,
            })

        # Any unpaired widgets beyond the shorter side's count -- surfaced
        # explicitly, never silently dropped.
        for i in range(n_pairs, n_r):
            rows.append({
                "chapter": chapter, "widget_index": i,
                "render_widget_id": r_widgets[i][0], "ref_widget_id": "ABSENT",
                "payload_bytes_render": len(r_widgets[i][1]), "payload_bytes_ref": "NA",
                "match": "no", "note": "render-only widget (ref has fewer widgets)",
            })
        for i in range(n_pairs, n_b):
            rows.append({
                "chapter": chapter, "widget_index": i,
                "render_widget_id": "ABSENT", "ref_widget_id": b_widgets[i][0],
                "payload_bytes_render": "NA", "payload_bytes_ref": len(b_widgets[i][1]),
                "match": "no", "note": "ref-only widget (render has fewer widgets)",
            })

    cols = ["chapter", "widget_index", "render_widget_id", "ref_widget_id",
            "payload_bytes_render", "payload_bytes_ref", "match", "note"]
    with open(out_tsv, "w") as f:
        f.write("\t".join(cols) + "\n")
        for row in rows:
            f.write("\t".join(str(row[c]) for c in cols) + "\n")

    chapters_with_widgets = sorted({r["chapter"] for r in rows if r["match"] in ("yes", "no")})
    total_pairs = sum(1 for r in rows if r["match"] in ("yes", "no"))
    total_matched = sum(1 for r in rows if r["match"] == "yes")
    total_mismatched = sum(1 for r in rows if r["match"] == "no")

    print(f"{len(chapters)} chapters scanned (49 book chapters + index)")
    print(f"{len(chapters_with_widgets)} chapters have >=1 widget on either side")
    print(f"{total_pairs} widget payloads compared: {total_matched} matched, {total_mismatched} mismatched")
    if count_mismatches:
        print(f"chapters with a DIFFERENT widget count render vs ref: {count_mismatches}")
    else:
        print("no chapter has a differing widget count between render and ref")
    if genuine_diffs:
        print(f"genuine post-normalization payload differences: {genuine_diffs}")
    else:
        print("no genuine payload differences after id-normalization")
    print(f"-> {out_tsv}")

    # ROUND 3 REMEDIATION: fail loud, matching compare_chapters.py /
    # compare_assets.py. Four independent conditions, all checked and all
    # reported together rather than stopping at the first one.
    failures = []
    if page_missing:
        failures.append(
            f"{len(page_missing)} chapter(s) with a MISSING page (render and/or "
            f"ref side did not exist -- its widgets could not be checked at all): "
            + "; ".join(f"{c}: {n}" for c, n in page_missing)
        )
    if total_pairs != EXPECTED_WIDGET_PAIRS:
        failures.append(
            f"expected {EXPECTED_WIDGET_PAIRS} widget payload pairs (README.md "
            f"'Inline widget payloads vs. book'), got {total_pairs}"
        )
    if count_mismatches:
        failures.append(
            f"{len(count_mismatches)} chapter(s) with a widget COUNT mismatch "
            f"render vs ref (structural -- never allowlisted): {count_mismatches}"
        )
    if unexplained:
        failures.append(
            f"{len(unexplained)} UNEXPLAINED widget payload mismatch(es), not on "
            f"ALLOWLIST: {unexplained}"
        )

    if failures:
        print(f"FAIL: {len(failures)} check(s) failed:")
        for msg in failures:
            print(f"  {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
