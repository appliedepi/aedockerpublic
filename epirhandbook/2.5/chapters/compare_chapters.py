#!/usr/bin/env python3
# Phase 3 comparison: each individually-rendered English chapter's HTML vs
# that same chapter's page from the Phase 2 full-book reference render.
#
# Uses diff_chapter.py's metric UNCHANGED (imported, not reimplemented): it
# strips <script>/<style>/tags, unescapes entities, normalizes ISO dates to
# the literal string DATE, collapses whitespace, then scores a word-level
# difflib.SequenceMatcher ratio over the whole page.
#
# Inputs:
#   - /p3/render_log.tsv        (chapter, status, seconds, note) from render_chapters.sh
#   - render_p3/html_outputs/   this run's own individual-chapter render
#   - ref_p2_book/              the Phase 2 full-book reference render (read-only; never written)
#
# Output: results.tsv (chapter, status, seconds, similarity_vs_book, note,
# rendered_sha16, ref_sha16, rendered_bytes, ref_bytes, rendered_path).
# similarity_vs_book is blank (not 0) for chapters with no book page to
# compare against -- see NO_BOOK_PAGE below for why each one has none. The
# sha16/bytes/path columns follow verify/manifest.tsv's sha16 convention
# (first 16 hex chars of sha256) -- added so results.tsv carries the same
# content provenance Phase 1/2's manifest.tsv already had; "NA" where a file
# does not exist on that side.
#
# FAIL-LOUD BEHAVIOR (exit code is non-zero if any of these trip):
#   1. Expected-count assertion: exactly 50 chapters (49 book chapters +
#      index) must produce a non-blank similarity_vs_book. A chapter that
#      HAS a book reference page but produced no score (see #2) breaks this.
#   2. Missing-file failure: a chapter that HAS a book reference page (i.e.
#      NOT in NO_BOOK_PAGE) but whose rendered HTML is absent from
#      html_outputs/ is a hard error, not a silent blank+note.
#   3. Threshold check: any book chapter scoring below FLOOR is a hard
#      error, UNLESS it is in VOLATILE_ALLOWLIST -- chapters already
#      documented (README.md) as legitimately variable run-to-run
#      (timestamp/session-info fields, or genuine stochastic content) so a
#      low score there is expected, not a regression signal.
#
# Usage: python3 compare_chapters.py <render_p3_dir> <ref_p2_book_dir> <render_log.tsv> <out_results.tsv>
import sys, os, hashlib, importlib.util, contextlib

def load_diff_chapter():
    # diff_chapter.py lives in ../verify/ (this repo's existing comparison
    # tooling, also mirrored at ~/ae/diff_chapter.py on compute) -- imported
    # here rather than copied, so there is exactly one copy of the metric.
    #
    # diff_chapter.py is a top-level SCRIPT, not a library: below its text()
    # def it immediately reads sys.argv and calls sys.exit(). Executing it
    # via exec_module would run that tail against OUR sys.argv and kill this
    # process. So: swap in harmless dummy argv (text() catches every
    # exception internally, so bogus paths just yield None), suppress the
    # SystemExit its "MISSING" branch raises, then restore real argv. Only
    # `mod.text` -- the actual metric, byte-for-byte as-is -- is used below;
    # nothing here reimplements or modifies it.
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "verify", "diff_chapter.py")
    spec = importlib.util.spec_from_file_location("diff_chapter", path)
    mod = importlib.util.module_from_spec(spec)
    real_argv = sys.argv
    sys.argv = ["diff_chapter.py", "/dev/null", "/dev/null", "x"]
    try:
        with contextlib.suppress(SystemExit), open(os.devnull, "w") as devnull, \
             contextlib.redirect_stdout(devnull):
            spec.loader.exec_module(mod)
    finally:
        sys.argv = real_argv
    return mod

# Chapters present as .qmd in new_pages/ but with NO corresponding page in
# ref_p2_book/new_pages/ -- i.e. not wired into _quarto.yml's book
# `chapters:` list, either explicitly excluded (commented out) or never
# referenced there at all (orphaned .qmd). Reconciles 67 English new_pages
# .qmd (+ index.qmd = 68 attempted) against the 49 pages in the book render.
NO_BOOK_PAGE = {
    "gis": "excluded from book (_quarto.yml, commented): fetches live OpenStreetMap tiles at render time",
    "plot_continuous": "excluded from book (_quarto.yml, commented): missing library(tidyr), drop_na not found",
    "plot_discrete": "excluded from book (_quarto.yml, commented): substantial real content; no reason stated in source",
    "relational_databases": "excluded from book (_quarto.yml, commented): THIS PAGE IS UNDER CONSTRUCTION stub",
    "rstudio_advanced": "excluded from book (_quarto.yml, commented): THIS PAGE IS UNDER CONSTRUCTION stub",
    "cat_about_book": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "cat_advanced": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "cat_analysis": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "cat_basics": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "cat_data_management": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "cat_data_viz": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "cat_introduction": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "cat_misc": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "cat_preview": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "cat_reports_dashboards": "never in _quarto.yml chapters: list: 1-line {.unnumbered} PART-divider stub",
    "apply_functions": "never in _quarto.yml chapters: list: template skeleton, no R code chunks",
    "descriptive_statistics": "never in _quarto.yml chapters: list: 932-line legacy page, superseded by tables_descriptive.qmd",
    "modeling": "never in _quarto.yml chapters: list: UNDER CONSTRUCTION stub, superseded by regression.qmd",
}

# Expect exactly 49 book chapters + index = 50 similarity scores.
EXPECTED_BOOK_CHAPTER_COUNT = 50

# Below this, a book chapter's score is treated as a regression unless it is
# in VOLATILE_ALLOWLIST. Set well below the lowest score any currently-
# understood, non-regression artifact produces (0.9740, stat_tests' gt-table
# id-escaping quirk -- see README.md) so a real content regression has to
# drop noticeably further than any known artifact to trip this, while still
# being far short of a meaningless floor like 0.0.
FLOOR = 0.95

# Chapters already documented (README.md) as legitimately scoring lower on
# SOME runs for reasons unrelated to content correctness: render-time/
# session-info fields that differ whenever the two compared renders happen
# on different days, or genuinely stochastic content. Named explicitly so
# the tolerance is visible here, not silent.
VOLATILE_ALLOWLIST = {
    "transmission_chains": "stochastic contact-network simulation, no fixed seed",
    "dates": "chapter teaches Sys.time()/Sys.Date() printing; differs whenever renders happen on different days",
    "directories": "prints fs::dir_info() mod-times and the render's own working directory path",
    "index": "date: today YAML front-matter field",
    "editorial_style": "prints session_info(); would differ if package/R/OS versions ever drifted",
}

def sha16(path):
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]
    except OSError:
        return "NA"

def size_or_na(path):
    try:
        return str(os.path.getsize(path))
    except OSError:
        return "NA"

def rendered_path(render_dir, chapter):
    # Book-member chapters (the 49 in _quarto.yml's `chapters:` list, + index)
    # render through the book pipeline into html_outputs/, honouring
    # output-dir. A chapter NOT in that list renders as a standalone quarto
    # document instead (quarto falls back to a plain `standalone: true` HTML
    # format for any target outside the active project's declared inputs),
    # and the output lands next to the source .qmd -- new_pages/<chapter>.html
    # -- NOT under html_outputs/. Both are real, on-disk HTML; only the
    # first has a book reference page to compare against (see NO_BOOK_PAGE).
    if chapter == "index":
        return os.path.join(render_dir, "html_outputs", "index.html")
    book_path = os.path.join(render_dir, "html_outputs", "new_pages", f"{chapter}.html")
    if os.path.exists(book_path):
        return book_path
    return os.path.join(render_dir, "new_pages", f"{chapter}.html")

def book_rendered_path(render_dir, chapter):
    # Strict form of rendered_path(), used ONLY for the missing-file check on
    # chapters that DO have a book reference page. No standalone-path
    # fallback: a book chapter must land in html_outputs/, so falling back to
    # new_pages/<chapter>.html here would risk masking a genuine missing
    # book-render behind an unrelated stray standalone file of the same name.
    if chapter == "index":
        return os.path.join(render_dir, "html_outputs", "index.html")
    return os.path.join(render_dir, "html_outputs", "new_pages", f"{chapter}.html")

def ref_path(ref_dir, chapter):
    if chapter == "index":
        return os.path.join(ref_dir, "index.html")
    return os.path.join(ref_dir, "new_pages", f"{chapter}.html")

def main():
    render_dir, ref_dir, log_tsv, out_tsv = sys.argv[1:5]
    dc = load_diff_chapter()

    rows = []
    with open(log_tsv) as f:
        header = f.readline()
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            chapter, status, seconds, note = (line.split("\t") + ["", "", "", ""])[:4]
            rows.append([chapter, status, seconds, note])

    errors = []       # hard failures: missing rendered HTML for a book chapter
    threshold_fails = []  # hard failures: book chapter scored below FLOOR, not allowlisted

    out = []
    for chapter, status, seconds, note in rows:
        rp = rendered_path(render_dir, chapter)
        rf = ref_path(ref_dir, chapter)
        sim = ""
        extra_note = note
        has_book_page = os.path.exists(rf)

        if not has_book_page:
            reason = NO_BOOK_PAGE.get(chapter, "no book page (reason not classified)")
            extra_note = (note + "; " if note else "") + reason
        else:
            strict_rp = book_rendered_path(render_dir, chapter)
            if not os.path.exists(strict_rp):
                msg = f"{chapter}: has a book reference page but no rendered HTML at {strict_rp}"
                errors.append(msg)
                extra_note = (note + "; " if note else "") + "ERROR: rendered HTML missing for a book chapter"
            elif status != "OK" or not os.path.exists(rp):
                extra_note = (note + "; " if note else "") + "render did not produce HTML to compare"
            else:
                a = dc.text(rp)
                b = dc.text(rf)
                if a is None or b is None:
                    extra_note = (note + "; " if note else "") + "diff_chapter.py could not read one side"
                else:
                    wa, wb = a.split(" "), b.split(" ")
                    import difflib
                    r = difflib.SequenceMatcher(None, wa, wb).ratio()
                    sim = f"{r:.4f}"
                    if r < FLOOR and chapter not in VOLATILE_ALLOWLIST:
                        threshold_fails.append(f"{chapter}: {sim} < floor {FLOOR}")

        r_sha = sha16(rp)
        b_sha = sha16(rf)
        r_bytes = size_or_na(rp)
        b_bytes = size_or_na(rf)
        out.append([chapter, status, seconds, sim, extra_note, r_sha, b_sha, r_bytes, b_bytes, rp])

    with open(out_tsv, "w") as f:
        f.write("chapter\tstatus\tseconds\tsimilarity_vs_book\tnote\trendered_sha16\tref_sha16\trendered_bytes\tref_bytes\trendered_path\n")
        for row in out:
            f.write("\t".join(row) + "\n")

    n = len(out)
    ok = sum(1 for r in out if r[1] == "OK")
    fail = sum(1 for r in out if r[1] != "OK")
    sims = [float(r[3]) for r in out if r[3] != ""]
    print(f"{n} chapters: {ok} OK, {fail} FAIL")
    print(f"{len(sims)} chapters compared to a book page (expected {EXPECTED_BOOK_CHAPTER_COUNT})")
    if sims:
        sims_sorted = sorted(sims)
        print(f"similarity: median={sims_sorted[len(sims_sorted)//2]:.4f} "
              f"min={sims_sorted[0]:.4f} max={sims_sorted[-1]:.4f} "
              f">=0.999: {sum(1 for s in sims if s >= 0.999)}/{len(sims)}")
    print(f"-> {out_tsv}")

    # --- fail loud ---
    ok_all = True
    if len(sims) != EXPECTED_BOOK_CHAPTER_COUNT:
        print(f"FAIL: expected {EXPECTED_BOOK_CHAPTER_COUNT} chapters with a similarity score, got {len(sims)}")
        ok_all = False
    if errors:
        print(f"FAIL: {len(errors)} book chapter(s) missing rendered HTML:")
        for e in errors:
            print(f"  {e}")
        ok_all = False
    if threshold_fails:
        print(f"FAIL: {len(threshold_fails)} book chapter(s) scored below floor {FLOOR} and are not in VOLATILE_ALLOWLIST:")
        for t in threshold_fails:
            print(f"  {t}")
        ok_all = False
    if not ok_all:
        sys.exit(1)

if __name__ == "__main__":
    main()
