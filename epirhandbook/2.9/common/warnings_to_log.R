# warnings_to_log.R -- the R_PROFILE_USER of every chapter render.
#
# build_all_chapters.sh starts each chapter container with
#   -e R_PROFILE_USER=/usr/local/lib/ehb/warnings_to_log.R
# and common/Dockerfile installs this file at that path. R reads it at the
# start of every R process in the container, which includes the one that
# Quarto starts to knit the chapter.
#
# WHAT IT DOES. Every R warning that a knitr chunk raises writes one line to
# stderr. So does every error that an `error: true` chunk captures:
#   EHB-WARNING<TAB><input file><TAB><chunk label><TAB><message>
#   EHB-ERROR<TAB><input file><TAB><chunk label><TAB><message>
# Newlines in the message become spaces, so one condition is one line.
# message() output is never logged. Quarto puts an ANSI colour code in front
# of the line, so strip those before you match '^EHB-'.
#
# WHY. A chunk with `warning: false` drops its warnings, and so does a page
# with `execute: warning: false`. R's own console report batches more than 10
# warnings into "There were 12 warnings". The build log then cannot say which
# chapter or chunk raised what.
#
# HOW. A knitr option hook, run at the start of every chunk, wraps knitr's
# `evaluate` hook. The wrap happens at chunk time because Quarto and
# rmarkdown set their own knitr hooks after knitr loads. The wrapper does
# three things:
#   1. It logs each warning and error that evaluate() captured. That covers
#      `warning: true`, the default, and `error: true`.
#   2. It passes keep_warning = NA where the chunk asked for FALSE. evaluate()
#      captures nothing for both values, so the captured output and the page
#      do not change. The only difference is that a warning under NA reaches
#      the calling handler around evaluate() instead of being dropped.
#   3. That calling handler logs each warning that evaluate() did not capture,
#      which covers `warning: false` and `warning: NA`. It then drops the
#      warning when the chunk asked for FALSE, as evaluate() would have.
# Each warning therefore reaches exactly one of (1) and (3).
#
# NOT COVERED:
#   - a chunk served from the knitr cache, because evaluate() does not run
#   - inline `r` code
#   - a warning that the chunk code muffles itself, as suppressWarnings() does
#
# R_PROFILE_USER replaces R's own search for a user profile, so R no longer
# reads a .Rprofile in the working directory. This file reads it instead.
local({
  if (file.exists(".Rprofile")) {
    source(".Rprofile")
  }

  log_condition <- function(kind, cnd) {
    input <- knitr::current_input()
    label <- knitr::opts_current$get("label")
    msg <- gsub("\r\n|\r|\n", " ", conditionMessage(cnd))
    cat(
      paste0(
        "EHB-", kind, "\t",
        if (is.null(input)) NA else input, "\t",
        if (is.null(label)) NA else label, "\t",
        msg, "\n"
      ),
      file = stderr()
    )
  }

  wrap_evaluate <- function(inner) {
    hook <- function(..., keep_warning = TRUE) {
      asked <- keep_warning
      if (isFALSE(keep_warning)) {
        keep_warning <- NA
      }
      res <- withCallingHandlers(
        inner(..., keep_warning = keep_warning),
        warning = function(w) {
          log_condition("WARNING", w)
          if (isFALSE(asked)) {
            tryInvokeRestart("muffleWarning")
          }
        }
      )
      for (x in res) {
        if (inherits(x, "warning")) {
          log_condition("WARNING", x)
        } else if (inherits(x, "error")) {
          log_condition("ERROR", x)
        }
      }
      res
    }
    attr(hook, "ehb") <- TRUE
    hook
  }

  install <- function(...) {
    knitr::opts_hooks$set(label = function(options) {
      current <- knitr::knit_hooks$get("evaluate")
      if (!isTRUE(attr(current, "ehb"))) {
        knitr::knit_hooks$set(evaluate = wrap_evaluate(current))
      }
      options
    })
  }

  if ("knitr" %in% loadedNamespaces()) {
    install()
  } else {
    setHook(packageEvent("knitr", "onLoad"), install)
  }
})
