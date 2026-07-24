#!/usr/bin/env Rscript
## rewrite_lang_config.R -- prepare ONE language's `_quarto.yml` before that
## language's chapters are rendered.
##
## WHY THIS EXISTS: rendering a translated `.qmd` against the unmodified
## English `_quarto.yml` fails SILENTLY -- `quarto render` exits 0, but the
## HTML lands next to its source file, outside `html_outputs/`, titled with
## the bare filename, tagged `<html lang="en">`, with no sidebar navigation,
## and carrying its own duplicated copy of the site's JS/CSS assets. Every
## chapter would "succeed" this way. Rewriting `_quarto.yml` for the target
## language BEFORE rendering fixes this completely: per-file renders then
## reproduce the whole-book output path-for-path. This script does exactly
## that rewrite, and nothing else -- it does not render anything.
##
## It ports (does not call) the config-rewrite half of
## quarto_runfile.R's render_quarto_lang()/use_lang_chapter(), which is
## itself a vendored copy of the R package babelquarto's internal logic
## (babelquarto's only EXPORTED entry points -- render_book(),
## render_website(), quarto_multilingual_book(),
## quarto_multilingual_website(), register_main_language(),
## register_further_languages(), confirmed via its NAMESPACE at the pinned
## commit -- drive an entire book render end to end via quarto::quarto_render();
## none of them rewrites `_quarto.yml` in isolation, so there is nothing to
## call here instead). The reference this script is based on:
## compute:~/ae/e0_spike/rewrite_lang_config.R.
##
## Idempotency warning (load-bearing): this rewrite is NOT idempotent.
## Running it twice on the same `_quarto.yml` turns "basics.fr.qmd" into
## "basics.fr.fr.qmd", and a second run may try to move a file that the
## first run already moved. ALWAYS run this against a fresh, pristine copy
## of the book -- never against a directory this script (or a prior
## language's run) has already touched.
##
## Usage:
##   Rscript rewrite_lang_config.R <project_dir> <language_code>
## Rewrites <project_dir>/_quarto.yml IN PLACE for <language_code>, moving
## any chapter with no translation on disk to its translated path (English
## content published under the translated URL -- see the warning this
## script emits for each chapter that happens to).

suppressPackageStartupMessages({
  library(rlang)
  library(readr)
  library(yaml)
  library(fs)
  library(withr)
  library(purrr)
  library(brio)
})

read_yaml_custom <- function(file) {
  string <- paste(readr::read_lines(file), collapse = "\n")
  yaml::yaml.load(string)
}

## Writing YAML back through R turns logical TRUE/FALSE into yes/no, which
## Quarto reads differently from true/false. This walks the parsed config
## and rewrites every logical into a "verbatim"-classed "true"/"false"
## string so yaml::write_yaml() emits it unquoted and unchanged. Preserved
## verbatim from the spike script -- dropping it silently breaks any
## boolean key in `_quarto.yml` (e.g. a `freeze:` or `cache:` flag).
replace_true_false <- function(x) {
  if (is.list(x)) {
    x <- lapply(x, replace_true_false)
  } else if (is.logical(x)) {
    x <- as.character(x)
    x <- gsub("TRUE", "true", x)
    x <- gsub("FALSE", "false", x)
    class(x) <- "verbatim"
  }
  x
}

## Rewrites one `book.chapters` entry (a single chapter path, OR a
## `part:`/`chapters:` group) to point at `language_code`'s translation.
## When the translated file does not exist on disk, FALLS BACK to the
## English source by MOVING (not copying) it onto the translated path --
## this is deliberately unchanged from quarto_runfile.R's behaviour, but
## now emits a warning naming the chapter, so a silent substitution becomes
## a visible one.
use_lang_chapter <- function(
  chapters_list,
  language_code,
  book_name,
  directory
) {
  withr::local_dir(file.path(directory, book_name))

  original_chapters_list <- chapters_list

  warn_fallback <- function(from, to) {
    warning(
      sprintf(
        "rewrite_lang_config.R: no '%s' translation for '%s' -- publishing the English source at '%s' instead.",
        language_code,
        from,
        to
      ),
      call. = FALSE,
      immediate. = TRUE
    )
  }

  if (is.list(chapters_list)) {
    chapters_list[["part"]] <- chapters_list[[sprintf(
      "part-%s",
      language_code
    )]] %||%
      chapters_list[["part"]]

    chapters_list$chapters <- gsub(
      "\\.Rmd",
      sprintf(".%s.Rmd", language_code),
      chapters_list$chapters
    )
    chapters_list$chapters <- gsub(
      "\\.qmd",
      sprintf(".%s.qmd", language_code),
      chapters_list$chapters
    )

    missing <- !fs::file_exists(chapters_list$chapters)
    if (any(missing)) {
      purrr::walk2(
        original_chapters_list$chapters[missing],
        chapters_list$chapters[missing],
        warn_fallback
      )
      fs::file_move(
        original_chapters_list$chapters[missing],
        chapters_list$chapters[missing]
      )
    }

    if (length(chapters_list$chapters) == 1) {
      chapters_list$chapters <- as.list(chapters_list$chapters)
    }
  } else {
    chapters_list <- gsub(
      "\\.Rmd",
      sprintf(".%s.Rmd", language_code),
      chapters_list
    )
    chapters_list <- gsub(
      "\\.qmd",
      sprintf(".%s.qmd", language_code),
      chapters_list
    )
    if (!fs::file_exists(file.path(directory, book_name, chapters_list))) {
      warn_fallback(original_chapters_list, chapters_list)
      fs::file_move(original_chapters_list, chapters_list)
    }
  }

  chapters_list
}

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2L) {
  cat(
    "usage: rewrite_lang_config.R <project_dir> <language_code>\n",
    file = stderr()
  )
  quit(status = 2L)
}
project_dir <- normalizePath(args[[1]], mustWork = TRUE)
language_code <- args[[2]]

cfg_path <- file.path(project_dir, "_quarto.yml")
if (!fs::file_exists(cfg_path)) {
  cat(
    sprintf("rewrite_lang_config.R: no _quarto.yml at '%s'\n", cfg_path),
    file = stderr()
  )
  quit(status = 2L)
}

## use_lang_chapter() below resolves each chapter path relative to
## file.path(directory, book_name) -- reconstruct that split from the
## single project_dir this script is given.
directory <- dirname(project_dir)
book_name <- basename(project_dir)

config <- read_yaml_custom(cfg_path)

config$lang <- language_code
config[["book"]][["title"]] <- config[[sprintf("title-%s", language_code)]] %||%
  config[["book"]][["title"]]
config[["book"]][["description"]] <- config[[sprintf(
  "description-%s",
  language_code
)]] %||%
  config[["book"]][["description"]]
config[["book"]][["author"]] <- config[[sprintf(
  "author-%s",
  language_code
)]] %||%
  config[["book"]][["author"]]

config[["book"]][["chapters"]] <- purrr::map(
  config[["book"]][["chapters"]],
  use_lang_chapter,
  language_code = language_code,
  book_name = book_name,
  directory = directory
)

config <- replace_true_false(config)
yaml::write_yaml(config, cfg_path)

## write_yaml() alone can leave platform-dependent line endings; round-trip
## through brio (as the spike script does) to normalise them.
config_lines <- brio::read_lines(cfg_path)
brio::write_lines(config_lines, cfg_path)

cat(sprintf(
  "rewrite_lang_config.R: rewrote '%s' for language '%s'\n",
  cfg_path,
  language_code
))
