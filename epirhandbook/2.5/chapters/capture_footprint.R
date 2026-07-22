# capture_footprint.R -- Phase 3 per-chapter package-footprint capture.
#
# Records the EMPIRICAL set of packages each chapter's render actually
# loaded, via loadedNamespaces() -- not a static grep of library()/p_load()
# calls in the .qmd source. This is the input to the Phase 5 per-chapter
# image split.
#
# MECHANISM
# Registers a knitr "document" hook. knitr calls this hook exactly once per
# render, after ALL of the .qmd's code chunks have already executed, passing
# the fully-knitted markdown as `x`; the hook must return `x`, which knitr
# then substitutes for the real output. This hook returns `x` UNCHANGED --
# its only effect is the side-effect file write below, so it cannot alter
# the rendered HTML. (Neutrality proven empirically: see README.md's
# "Instrumentation neutrality" section -- 3 chapters rendered with and
# without this file in place; all 3 scored diff_chapter.py similarity
# 1.0000 against their instrumented counterpart, and every underlying raw
# byte difference was traced to pre-existing per-render randomness in
# gt/htmlwidgets/quarto's JS bundling, unrelated to this hook.)
#
# WIRING (no handbook content is touched)
# This file is sourced from a one-line project .Rprofile
# (`source("capture_footprint.R")`) placed in the render_p3 working copy --
# never inside any .qmd. Rscript, which quarto/knitr shell out to for each
# chapter's actual execution, reads .Rprofile from the current working
# directory by default (verified empirically for this image/quarto combo).
# Each `quarto render` invocation is a fresh R process (quarto has no
# persistent R "kernel" for the knitr engine, unlike its Jupyter path), so
# loadedNamespaces() is never contaminated by a previous chapter.
#
# OUTPUT
# One file per chapter: /p3/footprints/<chapter>.txt, one package name per
# line, sorted. /p3 is a second bind mount (-v ~/ae/p3:/p3) entirely outside
# /book, so this write cannot be picked up by quarto's own project/book
# file-copying logic (asset tracking, _freeze, search index, etc).
#
# A chapter whose render FAILS (a chunk error under knitr's default
# error=FALSE) never reaches this hook -- knit() aborts before the document
# hook runs. That is expected: there is no valid "packages loaded so far"
# footprint to report for a chapter that didn't finish, so no file is
# written and footprints.tsv simply has no row for it.

if (requireNamespace("knitr", quietly = TRUE)) {
  knitr::knit_hooks$set(document = function(x) {
    tryCatch(
      {
        chapter <- tools::file_path_sans_ext(basename(knitr::current_input()))
        out_dir <- "/p3/footprints"
        dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)
        writeLines(
          sort(loadedNamespaces()),
          file.path(out_dir, paste0(chapter, ".txt"))
        )
      },
      error = function(e) {
        try(
          write(
            paste0(Sys.time(), " FOOTPRINT-HOOK-ERROR: ", conditionMessage(e)),
            "/p3/footprints/_hook_errors.log",
            append = TRUE
          ),
          silent = TRUE
        )
      }
    )
    x
  })
}
