#!/usr/bin/env Rscript
## inject_language_links.R -- the mandatory post-render pass: add the
## language-switcher dropdown (`<ul id="languages-links">`) to every HTML
## page in an ALREADY-ASSEMBLED output tree.
##
## WHY THIS EXISTS: the switcher is never produced by rendering. In a
## whole-book render it appears in 24 of 31 output files (the other 7 are
## meta-refresh redirect stubs whose targets already have it -- not a
## defect, and this script reproduces that: see the "no sidebar" skip
## branch inside add_dropdown_links() below). In a per-chapter render it
## appears in 0 of 31, because `quarto render` only
## ever sees ONE language's project at a time and has no way to know what
## other languages exist. This script runs once, after every language has
## been rendered and assembled into one tree, and walks every emitted
## `.html` file to add it.
##
## This PORTS (does not call) quarto_runfile.R's add_link(), itself a
## vendored copy of babelquarto's internal logic: babelquarto's own
## NAMESPACE (checked at the pinned commit, packages_github.json) exports
## only render_book(), render_website(), quarto_multilingual_book(),
## quarto_multilingual_website(), register_main_language() and
## register_further_languages() -- each of those drives an entire book
## render end to end via quarto::quarto_render(); none of them exposes a
## "just add the switcher to already-rendered HTML" entry point compatible
## with this repo's per-chapter-image architecture, so there is nothing to
## call instead of porting the logic.
##
## Two deliberate departures from the original while porting:
##
## 1. THE <li> BUG IS FIXED. The original builds `<a>` as a direct child of
##    the `<ul>`, then tries to wrap it in `<li>` with
##    `xml_add_parent(xml_find_first(html, "a[id='...']"), "li")`. That
##    XPath has no leading `//` AND uses `id='...'` as an ELEMENT-CHILD
##    test, not `@id='...'` (an attribute test) -- so it can never match
##    the anchor it just created, xml_add_parent() silently finds nothing
##    to wrap, and the `<li>` is never added. Browsers tolerate the bare
##    `<a>` inside a `<ul>`, but it is invalid list markup. This script
##    creates the `<li>` first and adds the `<a>` INSIDE it, so the output
##    is always `<ul><li><a>...</a></li></ul>`.
##
## 2. HREFS ARE NEVER ROOT-ABSOLUTE. The original builds every href as
##    `paste0(site_url, "/", path)`; when `site_url` is empty (the common
##    case -- and the spike's case), that still yields a leading "/", i.e.
##    a root-absolute path like "/fr/index.fr.html". That breaks the moment
##    the site is served from anything other than its domain root (a
##    deploy preview under a subpath, for instance). This script takes
##    `base_url` as an explicit, OPTIONAL argument:
##      - non-empty base_url  -> href = "<base_url>/<path-from-site-root>"
##        (root-relative to that base, same as the original when a real
##        site_url was supplied).
##      - empty base_url (the default) -> href is a TRUE relative path,
##        computed from the CURRENT page's own depth (site root vs. one
##        level down in <lang>/): "<path-from-site-root>" for a page at the
##        root, "../<path-from-site-root>" for a page already one level
##        down. This resolves correctly under ANY base path the site is
##        served from, including none.
##
## Assumes the fixed, 2-level tree shape build_all_chapters.sh's assembly
## step produces: the main language's pages sit directly at <site_dir>/*.html
## (English is the root, not html_outputs/en/), and every other language's
## pages sit at <site_dir>/<lang>/*.html. This script does not infer that
## shape generically; it is a stated contract with build_all_chapters.sh.
##
## Usage:
##   Rscript inject_language_links.R <site_dir> <quarto_yml> [<base_url>]
## <quarto_yml> is the PRISTINE (never rewritten) `_quarto.yml` -- only its
## babelquarto.mainlanguage / .languages / .languagecodes are read, for the
## language list and the dropdown's display labels.

suppressPackageStartupMessages({
  library(xml2)
  library(yaml)
  library(fs)
  library(purrr)
  library(rlang)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2L || length(args) > 3L) {
  cat(
    "usage: inject_language_links.R <site_dir> <quarto_yml> [<base_url>]\n",
    file = stderr()
  )
  quit(status = 2L)
}
site_dir <- normalizePath(args[[1]], mustWork = TRUE)
quarto_yml <- args[[2]]
base_url <- if (length(args) == 3L) sub("/$", "", args[[3]]) else ""

if (!fs::file_exists(quarto_yml)) {
  cat(
    sprintf("inject_language_links.R: no _quarto.yml at '%s'\n", quarto_yml),
    file = stderr()
  )
  quit(status = 2L)
}
config <- yaml::yaml.load(paste(readLines(quarto_yml), collapse = "\n"))

main_language <- config[["babelquarto"]][["mainlanguage"]]
language_codes <- config[["babelquarto"]][["languages"]]
if (is.null(main_language) || is.null(language_codes)) {
  cat(
    sprintf(
      "inject_language_links.R: '%s' is missing babelquarto.mainlanguage or babelquarto.languages\n",
      quarto_yml
    ),
    file = stderr()
  )
  quit(status = 2L)
}
codes_meta <- config[["babelquarto"]][["languagecodes"]] %||% list()

label_for <- function(lang) {
  hit <- purrr::keep(codes_meta, ~ identical(.x[["name"]], lang))
  if (length(hit) > 0 && !is.null(hit[[1]][["text"]])) {
    hit[[1]][["text"]]
  } else {
    sprintf("Version in %s", toupper(lang))
  }
}

## target_rel_from_root(): the emitted path of `lang`'s version of a page,
## relative to site_dir -- "time_series.html" for the main language,
## "fr/time_series.fr.html" for French. `filename_main` is always the
## MAIN-LANGUAGE (lang-infix-free) filename; every other language's file
## name is derived from it, never stored separately.
target_rel_from_root <- function(lang, filename_main) {
  if (identical(lang, main_language)) {
    filename_main
  } else {
    file.path(lang, sub("\\.html$", sprintf(".%s.html", lang), filename_main))
  }
}

## href_for(): see departure (2) in the header comment.
href_for <- function(current_is_main, target_lang, filename_main) {
  target <- target_rel_from_root(target_lang, filename_main)
  if (nzchar(base_url)) {
    paste0(base_url, "/", target)
  } else if (current_is_main) {
    target
  } else {
    file.path("..", target)
  }
}

## add_dropdown_links(): mutate ONE HTML file in place, adding an <li><a>
## entry per target language. `targets` is a named list, target language
## code -> that page's main-language (infix-free) filename.
add_dropdown_links <- function(path, current_is_main, targets) {
  html <- xml2::read_html(path)

  sidebar <- xml2::xml_find_first(
    html,
    "//div[contains(@class,'sidebar-header')]"
  )
  if (inherits(sidebar, "xml_missing")) {
    ## Meta-refresh redirect stubs have no sidebar at all -- expected (see
    ## header comment); skip rather than fail the whole pass over one file.
    message(
      "inject_language_links.R: no sidebar in ",
      path,
      " -- skipping (redirect stub)"
    )
    return(invisible(NULL))
  }

  ul <- xml2::xml_find_first(html, "//ul[@id='languages-links']")
  if (inherits(ul, "xml_missing")) {
    xml2::xml_add_sibling(
      sidebar,
      "div",
      class = "dropdown",
      id = "languages-links-parent",
      .where = "after"
    )
    parent <- xml2::xml_find_first(html, "//div[@id='languages-links-parent']")
    btn <- xml2::xml_add_child(
      parent,
      "button",
      "",
      class = "btn btn-primary dropdown-toggle",
      type = "button",
      `data-bs-toggle` = "dropdown",
      `aria-expanded` = "false",
      id = "languages-button"
    )
    xml2::xml_add_child(btn, "i", class = "bi bi-globe2")
    ul <- xml2::xml_add_child(
      parent,
      "ul",
      class = "dropdown-menu",
      id = "languages-links"
    )
  }

  for (lang in names(targets)) {
    li <- xml2::xml_add_child(ul, "li")
    xml2::xml_add_child(
      li,
      "a",
      label_for(lang),
      class = "dropdown-item",
      href = href_for(current_is_main, lang, targets[[lang]]),
      id = sprintf("language-link-%s", lang)
    )
  }

  xml2::write_html(html, path)
}

main_docs <- fs::dir_ls(site_dir, glob = "*.html", recurse = FALSE)
lang_docs <- purrr::map(language_codes, function(l) {
  d <- file.path(site_dir, l)
  if (fs::dir_exists(d)) {
    fs::dir_ls(d, glob = "*.html", recurse = FALSE)
  } else {
    character(0)
  }
})
names(lang_docs) <- language_codes

## Main-language pages: one link to every OTHER language.
for (doc in main_docs) {
  fname <- basename(doc)
  targets <- stats::setNames(
    as.list(rep(fname, length(language_codes))),
    language_codes
  )
  add_dropdown_links(doc, current_is_main = TRUE, targets = targets)
}

## Each other language's pages: one link back to the main language, plus one
## link to every OTHER translated language -- never to itself.
for (lang in language_codes) {
  others <- c(main_language, setdiff(language_codes, lang))
  for (doc in lang_docs[[lang]]) {
    base_fname <- sub(sprintf("\\.%s\\.html$", lang), ".html", basename(doc))
    targets <- stats::setNames(as.list(rep(base_fname, length(others))), others)
    add_dropdown_links(doc, current_is_main = FALSE, targets = targets)
  }
}

cat(sprintf(
  "inject_language_links.R: done -- %d main-language page(s), %d translated page(s) across %d language(s)\n",
  length(main_docs),
  sum(lengths(lang_docs)),
  length(language_codes)
))
