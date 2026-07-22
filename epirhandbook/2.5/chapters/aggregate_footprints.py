#!/usr/bin/env python3
# Phase 3 footprint aggregator: turns capture_footprint.R's per-chapter output
# (one /p3/footprints/<chapter>.txt per chapter, one loaded namespace per
# line, already sort()-ed by R) into the single footprints.tsv deliverable.
#
# This is the missing link the codex review flagged: capture_footprint.R
# writes the per-chapter .txt dumps, but nothing in the repo turned those
# into footprints.tsv -- that file was produced by an ad-hoc step that no
# longer exists. This script is that step, made reproducible.
#
# Packages are re-sorted here with Python's builtin sorted() (codepoint /
# ASCII order: 'A'-'Z' before 'a'-'z'), NOT left in the .txt file's own line
# order. R's sort(loadedNamespaces()) uses the process locale's collation,
# which on this image sorts case-insensitively (e.g. ...digest,dplyr,DT,
# evaluate...) -- verified to differ from the committed footprints.tsv's own
# row order (...DT,R.methodsS3,...,apyramid,base,...), which matches
# sorted()'s ASCII order exactly. Re-sorting with sorted() here reproduces
# the committed file byte-for-byte; preserving .txt line order would not.
#
# ROUND-2 REMEDIATION (Task 4): this script used to silently IGNORE hook
# errors (skip _hook_errors.log without ever checking whether it had
# content) and silently accepted ANY chapter missing a footprint, with no
# way to tell "this chapter legitimately has zero R chunks" apart from "the
# hook failed / a chapter that should have a footprint doesn't". It now:
#   1. FAILS if /p3/footprints/_hook_errors.log exists at all (capture_
#      footprint.R only ever writes to it from inside its hook's own
#      tryCatch error handler -- its mere existence means the hook threw
#      for at least one chapter, which means that chapter's footprint, if
#      any exists, may be incomplete/stale rather than absent).
#   2. Takes render_log.tsv (render_chapters.sh's own OK/FAIL record) as a
#      required third input, and for every chapter marked OK there, asserts
#      it either has a footprint OR is on the explicit ZERO_R_CHUNK_CHAPTERS
#      list (chapters independently confirmed, by grepping their .qmd
#      source for zero ```{r chunks, to need no packages to render -- see
#      README.md "Package footprints"). Any OTHER OK chapter missing a
#      footprint is now a hard error, not a silent gap. A chapter that
#      FAILED to render is expected to have no footprint regardless (see
#      capture_footprint.R: the hook never runs for an aborted render) and
#      is not held to this check.
#
# Usage: python3 aggregate_footprints.py <footprints_dir> <render_log.tsv> <out_tsv>
import sys
import os
import glob

# Confirmed (both by README.md's own investigation and independently
# re-verified here by grepping each .qmd for '```{r' chunks: all 14 return
# zero) to contain no executable R chunks, so knitr never runs for them and
# the footprint hook never fires -- not a capture gap.
ZERO_R_CHUNK_CHAPTERS = {
    "cat_about_book", "cat_advanced", "cat_analysis", "cat_basics",
    "cat_data_management", "cat_data_viz", "cat_introduction", "cat_misc",
    "cat_preview", "cat_reports_dashboards",
    "apply_functions", "modeling", "rstudio_advanced", "errors",
}


def load_chapter(path):
    with open(path, encoding="utf-8") as f:
        pkgs = [line.strip() for line in f if line.strip()]
    return sorted(pkgs)


def load_render_log(path):
    rows = {}
    with open(path, encoding="utf-8") as f:
        header = f.readline()
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            chapter, status = parts[0], parts[1]
            rows[chapter] = status
    return rows


def main():
    footprints_dir, render_log_tsv, out_tsv = sys.argv[1:4]

    # --- 1. fail loud on any recorded hook error ---
    hook_errors_path = os.path.join(footprints_dir, "_hook_errors.log")
    if os.path.exists(hook_errors_path):
        with open(hook_errors_path, encoding="utf-8") as f:
            contents = f.read()
        print(f"FAIL: {hook_errors_path} exists -- the footprint-capture hook itself "
              f"threw an error for at least one chapter render:")
        print(contents)
        sys.exit(1)

    chapters = []
    footprint_chapters = set()
    for path in sorted(glob.glob(os.path.join(footprints_dir, "*.txt"))):
        chapter = os.path.splitext(os.path.basename(path))[0]
        pkgs = load_chapter(path)
        chapters.append((chapter, pkgs))
        footprint_chapters.add(chapter)

    with open(out_tsv, "w") as f:
        f.write("chapter\tn_packages\tpackages\n")
        for chapter, pkgs in chapters:
            f.write(f"{chapter}\t{len(pkgs)}\t{','.join(pkgs)}\n")

    all_pkgs = set()
    for _, pkgs in chapters:
        all_pkgs.update(pkgs)
    counts = sorted(len(pkgs) for _, pkgs in chapters)
    print(f"{len(chapters)} chapters with a footprint")
    print(f"{len(all_pkgs)} distinct namespaces across all chapters")
    if counts:
        n = len(counts)
        median = counts[n // 2] if n % 2 else (counts[n // 2 - 1] + counts[n // 2]) / 2
        print(f"per-chapter package count: min={counts[0]} median={median} max={counts[-1]}")
    print(f"-> {out_tsv}")

    # --- 2. assert every OK chapter missing a footprint is a classified
    #        zero-R-chunk chapter; anything else missing is an error ---
    render_log = load_render_log(render_log_tsv)
    unexplained_missing = []
    for chapter, status in sorted(render_log.items()):
        if status != "OK":
            continue  # a chapter that failed to render is expected to have no footprint
        if chapter in footprint_chapters:
            continue
        if chapter in ZERO_R_CHUNK_CHAPTERS:
            continue
        unexplained_missing.append(chapter)

    classified_and_missing = sorted(
        c for c in ZERO_R_CHUNK_CHAPTERS
        if render_log.get(c) == "OK" and c not in footprint_chapters
    )
    print(f"{len(classified_and_missing)}/{len(ZERO_R_CHUNK_CHAPTERS)} classified "
          f"zero-R-chunk chapters confirmed missing a footprint (expected, not an error)")

    if unexplained_missing:
        print(f"FAIL: {len(unexplained_missing)} chapter(s) rendered OK, are NOT on the "
              f"zero-R-chunk allowlist, but produced no footprint:")
        for c in unexplained_missing:
            print(f"  {c}")
        sys.exit(1)


if __name__ == "__main__":
    main()
