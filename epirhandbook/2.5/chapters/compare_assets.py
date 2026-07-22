#!/usr/bin/env python3
# Phase 3 asset comparison v2: hashes AND genuinely pixel-diffs each chapter's
# generated asset directory (figure-html PNGs, htmlwidget dependency files,
# anything quarto writes to <chapter>_files/) on both sides, so figures/
# widgets are covered too -- compare_chapters.py / diff_chapter.py only ever
# looked at page TEXT.
#
# WHAT CHANGED FROM v1 (second adversarial review, round 2, found both bugs):
#   1. v1's KNOWN_RANDOM dict hardcoded a one-sentence causal explanation per
#      CHAPTER and printed it for every mismatch in that chapter, regardless
#      of the actual file. That is not classification, it is asserting a
#      pre-written conclusion -- and one of those conclusions was WRONG:
#      epidemic_models was asserted to be a "render-date artifact" (forecast
#      anchored to render date). The round-2 remediation's A/A re-render test
#      (two trees, same day, identical instrumentation, only run-identity
#      differing -- see README.md "Task 1") proved by direct experiment that
#      the same two epidemic_models figures differ RUN TO RUN even on a
#      single day, and become byte-identical once `set.seed()` is added. The
#      real cause is unseeded rgamma()/project(), not the render date. A tool
#      that bakes in a causal story as fact is exactly how a wrong
#      explanation like that goes unchallenged. v2 computes only what it can
#      actually measure (pixel_diff_pct, pixels_differing, pixels_total,
#      whether dimensions match) and separately reports whether a chapter is
#      on an explicit ALLOWLIST, with a pointer to where the justification
#      lives -- it does not assert a mechanism as this script's own finding.
#   2. v1's docstring mentioned PIL.ImageChops but the code only ever called
#      hashlib -- no pixel diffing ever ran. The percentages that appeared in
#      the committed assets.tsv and README.md were computed by hand, outside
#      this script, and were not reproducible from the repo. v2 actually
#      calls PIL on every mismatching image pair and writes the result as
#      real columns (pixel_diff_pct, pixels_differing, pixels_total),
#      dimensions_match, and byte sizes on both sides.
#   3. v1 only ever hashed, with no distinction between an image and any
#      other file type. v2 tags every file's `kind` (image/non-image) and
#      the summary reports the two separately. Non-image files (.js/.css/
#      .json/anything else) are still compared by hash only -- pixel-diffing
#      does not apply to them. (In the current dataset every _files/ file
#      happens to be a PNG -- htmlwidget JS/JSON in this handbook is inlined
#      into the chapter's own HTML, not written to _files/, which is exactly
#      why Task 3 / compare_widgets.py exists as a separate check -- but the
#      non-image path here is real code, not a stub, for any chapter/render
#      where it would apply.)
#   4. v1 never exited non-zero. v2 fails loud: ANY mismatch (or file present
#      on only one side) in a chapter that is not on the explicit ALLOWLIST
#      is a hard error.
#
# assets.tsv is now ONE ROW PER FILE (not one row per chapter), because
# pixel_diff_pct/pixels_differing/pixels_total are inherently per-file
# quantities -- summing or averaging them across a chapter's files would not
# mean anything. The `chapter` column is kept so a per-chapter rollup is a
# one-line groupby away, and the script's own stdout summary reports the same
# chapter-count/file-count/matched/mismatched totals v1 reported, so the
# headline numbers stay directly comparable.
#
# ROUND 3 REMEDIATION (third adversarial review) supersedes the paragraph
# above: chapter-grained was not a defensible design choice, it was a bug.
# ALLOWLIST.get(chapter) waved through EVERY file in an allowlisted chapter,
# not just the ones ever observed to mismatch. Concretely, in the assets.tsv
# this produced before this fix, 109 rows were marked "allowlisted: yes" --
# 100 of them files that already matched byte-for-byte and never needed an
# allowlist entry at all (e.g. ggplot_tips alone contributes 41 of those
# rows, only 3 of which are real mismatches) -- while only 9 rows were
# actual mismatches. A NEW mismatch in any of the other 100 files (a 4th
# ggplot_tips figure genuinely corrupted, say) would have been waved through
# identically to the 9 real, documented cases. ALLOWLIST is now keyed by the
# EXACT (chapter, path) of each of the 9 mismatches actually observed --
# nothing else is tolerated implicitly, including a new mismatch inside one
# of these same six chapters.
#
# Usage: python3 compare_assets.py <render_dir> <ref_dir> <out_tsv>
# The 49 book chapters are derived from ref_dir itself (every new_pages/*.html
# there IS, by definition, a book chapter -- ref_p2_book only ever contains
# book pages) -- not from a separately-maintained list that could drift out
# of sync with the book. "index" is always added automatically as chapter 50.
import sys
import os
import glob
import hashlib

try:
    from PIL import Image, ImageChops
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}

# Files documented in README.md as legitimately varying run-to-run. Keyed by
# the EXACT (chapter, path) of each of the 9 mismatches observed in
# assets.tsv -- not by chapter (see ROUND 3 REMEDIATION note above). Every
# entry states, explicitly, whether the cause was CONFIRMED by a direct
# re-render experiment (README.md "Task 1": two figures, re-rendered twice
# with set.seed() added, byte-identical both times) or is source-inspection-
# only (the mechanism is visible in the chapter's .qmd -- an unseeded RNG
# call with no set.seed() anywhere -- but not independently re-rendered to
# prove it). Either way this is a POINTER to where the justification lives,
# not a claim this script verifies on its own; note transmission_chains is
# deliberately NOT in this dict -- its 2 figures hash identical in this
# dataset (see README.md), so it has no observed mismatch to allow, and a
# newly-differing transmission_chains figure should fail like anything else.
ALLOWLIST = {
    ("age_pyramid", "figure-html/unnamed-chunk-22-1.png"): {
        "classification": "source-inspection-only",
        "evidence": "README.md 'Generated assets (figures) vs. book': Sys.Date() "
                    "interpolated into a plot caption string -- same render-date "
                    "root cause independently confirmed for dates/index/directories "
                    "(page-text checks); not re-verified here by a dedicated "
                    "re-render test of this specific image",
    },
    ("combination_analysis", "figure-html/unnamed-chunk-1-1.png"): {
        "classification": "source-inspection-only",
        "evidence": "README.md 'Generated assets (figures) vs. book': "
                    "sample(c(\"yes\",\"no\"), ..., prob=...) generates the "
                    "chapter's demo symptom columns fresh every render; no "
                    "set.seed() anywhere in the chapter source",
    },
    ("epidemic_models", "figure-html/epidemic_models_plot_projection-1.png"): {
        "classification": "confirmed",
        "evidence": "README.md 'Task 1: settling run-to-run vs. instrumentation': "
                    "A/A re-render test + set.seed() experiment directly proved "
                    "unseeded rgamma()/project(), run-to-run",
    },
    ("epidemic_models", "figure-html/epidemic_models_projection_setup-1.png"): {
        "classification": "confirmed",
        "evidence": "README.md 'Task 1: settling run-to-run vs. instrumentation': "
                    "A/A re-render test + set.seed() experiment directly proved "
                    "unseeded rgamma()/project(), run-to-run",
    },
    ("ggplot_basics", "figure-html/unnamed-chunk-40-1.png"): {
        "classification": "confirmed",
        "evidence": "README.md 'Task 1: settling run-to-run vs. instrumentation': "
                    "A/A re-render test + set.seed() experiment directly proved "
                    "unseeded geom_jitter()/geom_sina(), run-to-run",
    },
    ("ggplot_basics", "figure-html/unnamed-chunk-41-1.png"): {
        "classification": "confirmed",
        "evidence": "README.md 'Task 1: settling run-to-run vs. instrumentation': "
                    "A/A re-render test + set.seed() experiment directly proved "
                    "unseeded geom_jitter()/geom_sina(), run-to-run",
    },
    ("ggplot_tips", "figure-html/unnamed-chunk-23-1.png"): {
        "classification": "source-inspection-only",
        "evidence": "README.md 'Generated assets (figures) vs. book': unseeded "
                    "ggrepel::geom_label_repel() stochastic label-repulsion "
                    "layout; no set.seed() anywhere in the chapter source",
    },
    ("ggplot_tips", "figure-html/unnamed-chunk-24-1.png"): {
        "classification": "source-inspection-only",
        "evidence": "README.md 'Generated assets (figures) vs. book': unseeded "
                    "ggrepel::geom_label_repel() stochastic label-repulsion "
                    "layout; no set.seed() anywhere in the chapter source",
    },
    ("ggplot_tips", "figure-html/unnamed-chunk-28-1.png"): {
        "classification": "source-inspection-only",
        "evidence": "README.md 'Generated assets (figures) vs. book': 0.0007% "
                    "(9 of 1,290,240 pixels) -- antialiasing-scale rendering "
                    "noise, not a content difference",
    },
}

# Upper bound on how different an ALLOWLISTED image may be before it stops being
# "the known run-to-run variation" and becomes something else.
#
# WHY THIS EXISTS: an allowlist entry says "this exact file is expected to differ
# for a documented reason". Without a bound it says "this file may differ by ANY
# amount, for any reason" -- so replacing an allowlisted figure with a corrupt
# file, an image of different dimensions, or a completely unrelated picture would
# still be recorded as `mismatch`, hit the allowlist, and exit 0. Bounded
# tolerance is the point; unbounded tolerance is a hole.
#
# The ceilings are deliberately GENEROUS (roughly 2.5x the observed value, floored
# at 5%), because several of these figures are genuinely stochastic and a future
# render may legitimately differ more than the run recorded in assets.tsv. They
# are sized to catch corruption and wholesale replacement, NOT to police the exact
# variance of a random draw. Tightening them would produce false failures on an
# honest re-render, which is the failure mode that destroys trust in a gate.
#
# Alongside this, an allowlisted image must still be READABLE by PIL and have
# MATCHING DIMENSIONS -- both are enforced below, and neither is allowlistable.
MAX_PIXEL_DIFF_PCT = {
    ("age_pyramid", "figure-html/unnamed-chunk-22-1.png"): 5.0,           # observed 0.0130
    ("combination_analysis", "figure-html/unnamed-chunk-1-1.png"): 7.0,   # observed 2.7228
    ("epidemic_models", "figure-html/epidemic_models_plot_projection-1.png"): 5.0,   # observed 0.8311
    ("epidemic_models", "figure-html/epidemic_models_projection_setup-1.png"): 41.0, # observed 16.4060
    ("ggplot_basics", "figure-html/unnamed-chunk-40-1.png"): 35.0,        # observed 13.7939
    ("ggplot_basics", "figure-html/unnamed-chunk-41-1.png"): 27.0,        # observed 10.7425
    ("ggplot_tips", "figure-html/unnamed-chunk-23-1.png"): 9.0,           # observed 3.3438
    ("ggplot_tips", "figure-html/unnamed-chunk-24-1.png"): 5.0,           # observed 0.6625
    ("ggplot_tips", "figure-html/unnamed-chunk-28-1.png"): 5.0,           # observed 0.0007
}

# Keep the two tables in lockstep. An allowlist entry without a bound would
# silently reintroduce unbounded tolerance for that path.
assert set(MAX_PIXEL_DIFF_PCT) == set(ALLOWLIST), (
    "MAX_PIXEL_DIFF_PCT and ALLOWLIST must cover exactly the same paths; "
    f"only in ALLOWLIST: {sorted(set(ALLOWLIST) - set(MAX_PIXEL_DIFF_PCT))}; "
    f"only in MAX_PIXEL_DIFF_PCT: {sorted(set(MAX_PIXEL_DIFF_PCT) - set(ALLOWLIST))}"
)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def kind_of(rel):
    ext = os.path.splitext(rel)[1].lower()
    return "image" if ext in IMAGE_EXT else "non-image"


def pixel_diff(path_a, path_b):
    """Actually run PIL.ImageChops.difference and return real counts.
    Returns (dimensions_match, pixel_diff_pct, pixels_differing, pixels_total, note).

    Converts to RGB, not RGBA. Pillow's Image.getbbox() defaults to
    alpha-only bounding-box detection for images that carry an alpha
    channel (Pillow >= 9.2): if both images are the same opaque RGB figure
    converted to RGBA, alpha is a uniform 255 on both sides, so the alpha
    CHANNEL of the diff is uniformly 0 even when R/G/B genuinely differ --
    getbbox() then reports "no difference" while extrema shows otherwise.
    (Caught empirically while regenerating assets.tsv: every one of the 9
    known mismatches came back 0.0000% under RGBA before this fix, silently
    wrong.) Every figure this script has ever compared is plain opaque RGB
    (verified: PIL reports mode "RGB", not "RGBA"/"P", for all of them), so
    converting to RGB and never relying on getbbox() as a shortcut is both
    correct here and avoids the trap. A genuinely transparent source image
    would need different handling; none exists in this dataset.
    """
    if not HAVE_PIL:
        return ("NA", "NA", "NA", "NA", "PIL not available -- pixel diff not computed")
    try:
        ia = Image.open(path_a).convert("RGB")
        ib = Image.open(path_b).convert("RGB")
    except Exception as e:
        return ("NA", "NA", "NA", "NA", f"PIL could not open image(s): {e}")

    if ia.size != ib.size:
        return ("no", "NA", "NA", "NA",
                f"dimensions differ: render={ia.size[0]}x{ia.size[1]} ref={ib.size[0]}x{ib.size[1]} -- pixel diff not meaningful")

    diff = ImageChops.difference(ia, ib)
    w, h = ia.size
    total = w * h
    differing = sum(1 for px in diff.getdata() if any(px))
    pct = (differing / total * 100) if total else 0.0
    return ("yes", f"{pct:.4f}", differing, total, "")


def files_dir(base, chapter, under_new_pages):
    if chapter == "index":
        return os.path.join(base, "index_files")
    sub = os.path.join(base, "new_pages") if under_new_pages else base
    return os.path.join(sub, f"{chapter}_files")


def walk_paths(root):
    out = {}
    if not os.path.isdir(root):
        return out
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            out[rel] = full
    return out


def main():
    render_dir, ref_dir, out_tsv = sys.argv[1:4]

    book_html = sorted(glob.glob(os.path.join(ref_dir, "new_pages", "*.html")))
    chapters = [os.path.splitext(os.path.basename(p))[0] for p in book_html]
    chapters = chapters + ["index"]

    rows = []
    unexplained = []

    for chapter in chapters:
        r_dir = files_dir(os.path.join(render_dir, "html_outputs"), chapter, under_new_pages=True)
        b_dir = files_dir(ref_dir, chapter, under_new_pages=True)

        r_files = walk_paths(r_dir)
        b_files = walk_paths(b_dir)
        all_paths = sorted(set(r_files) | set(b_files))

        for rel in all_paths:
            in_r, in_b = rel in r_files, rel in b_files
            kind = kind_of(rel)
            dims_match = pct = differing = total = "NA"
            note = ""

            if in_r and in_b:
                rpath, bpath = r_files[rel], b_files[rel]
                rsize, bsize = os.path.getsize(rpath), os.path.getsize(bpath)
                rsha, bsha = sha256(rpath), sha256(bpath)
                if rsha == bsha:
                    status = "match"
                else:
                    status = "mismatch"
                    if kind == "image":
                        dims_match, pct, differing, total, note = pixel_diff(rpath, bpath)
                    else:
                        note = "non-image file content differs (sha256 mismatch); not pixel-diffable"
            elif in_r:
                status = "render-only"
                rsize, bsize = os.path.getsize(r_files[rel]), "NA"
                rsha, bsha = sha256(r_files[rel]), "NA"
                note = "present in render, absent from ref"
            else:
                status = "ref-only"
                rsize, bsize = "NA", os.path.getsize(b_files[rel])
                rsha, bsha = "NA", sha256(b_files[rel])
                note = "present in ref, absent from render"

            allow_entry = ALLOWLIST.get((chapter, rel))
            if status == "match":
                classification = ""
            elif status in ("render-only", "ref-only"):
                # A file present on only ONE side is a broken comparison, never a
                # tolerable content difference. The allowlist exists to excuse known
                # run-to-run CONTENT variation between two files that both exist -- it
                # must never excuse a figure that vanished. Applying it here would mean
                # deleting an allowlisted figure outright still exits 0.
                classification = (f"FATAL {status} -- allowlist applies to content "
                                  f"mismatches only, never to a missing file")
                if note:
                    classification += f"; {note}"
                unexplained.append((chapter, rel))
            elif allow_entry:
                # An allowlist entry excuses a KNOWN, BOUNDED difference. Verify the
                # difference actually is that, rather than trusting the path alone:
                # the image must be readable, the same size, and within its ceiling.
                # None of these three is itself allowlistable.
                breaches = []
                if kind == "image":
                    if pct == "NA":
                        breaches.append("pixel diff unavailable -- image unreadable, "
                                        "corrupt, or not comparable")
                    elif float(pct) > MAX_PIXEL_DIFF_PCT[(chapter, rel)]:
                        breaches.append(f"pixel diff {pct}% exceeds this path's documented "
                                        f"ceiling {MAX_PIXEL_DIFF_PCT[(chapter, rel)]}%")
                    if dims_match != "yes":
                        breaches.append(f"image dimensions differ (dimensions_match={dims_match})")
                else:
                    breaches.append("non-image file at an allowlisted path -- the allowlist "
                                    "documents figure variation only")
                if breaches:
                    classification = ("FATAL allowlisted path outside its documented bound -- "
                                      + "; ".join(breaches))
                    if note:
                        classification += f"; {note}"
                    unexplained.append((chapter, rel))
                else:
                    classification = (f"allowlisted ({allow_entry['classification']}) -- "
                                      f"{allow_entry['evidence']}")
                    if note:
                        classification += f"; {note}"
            else:
                classification = "UNEXPLAINED mismatch -- not on allowlist"
                if note:
                    classification += f"; {note}"
                unexplained.append((chapter, rel))

            rows.append({
                "chapter": chapter, "path": rel, "kind": kind, "status": status,
                "render_bytes": rsize, "ref_bytes": bsize,
                "render_sha16": (rsha[:16] if rsha != "NA" else "NA"),
                "ref_sha16": (bsha[:16] if bsha != "NA" else "NA"),
                "dimensions_match": dims_match, "pixel_diff_pct": pct,
                "pixels_differing": differing, "pixels_total": total,
                "allowlisted": "yes" if allow_entry else "no",
                "classification": classification,
            })

    cols = ["chapter", "path", "kind", "status", "render_bytes", "ref_bytes",
            "render_sha16", "ref_sha16", "dimensions_match", "pixel_diff_pct",
            "pixels_differing", "pixels_total", "allowlisted", "classification"]
    with open(out_tsv, "w") as f:
        f.write("\t".join(cols) + "\n")
        for row in rows:
            f.write("\t".join(str(row[c]) for c in cols) + "\n")

    img_rows = [r for r in rows if r["kind"] == "image"]
    nonimg_rows = [r for r in rows if r["kind"] == "non-image"]
    matched = sum(1 for r in rows if r["status"] == "match")
    mismatched = sum(1 for r in rows if r["status"] != "match")
    img_mismatched = sum(1 for r in img_rows if r["status"] != "match")
    nonimg_mismatched = sum(1 for r in nonimg_rows if r["status"] != "match")

    print(f"{len(chapters)} chapters compared (49 book chapters + index)")
    print(f"{len(rows)} files total: {len(img_rows)} image, {len(nonimg_rows)} non-image")
    print(f"images: {len(img_rows) - img_mismatched} matched, {img_mismatched} mismatched")
    print(f"non-image: {len(nonimg_rows) - nonimg_mismatched} matched, {nonimg_mismatched} mismatched")
    print(f"ALL: {matched} matched, {mismatched} mismatched")
    chapters_with_mismatch = sorted({r["chapter"] for r in rows if r["status"] != "match"})
    print(f"chapters with >=1 mismatch: {chapters_with_mismatch}")
    print(f"-> {out_tsv}")

    if unexplained:
        print(f"FAIL: {len(unexplained)} mismatch(es) not on the allowlist:")
        for chapter, rel in unexplained:
            print(f"  {chapter}: {rel}")
        sys.exit(1)


if __name__ == "__main__":
    main()
