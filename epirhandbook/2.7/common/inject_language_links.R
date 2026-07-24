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
##        computed with fs::path_rel() from the CURRENT page's own directory,
##        so it is right at ANY depth. This resolves correctly under any base
##        path the site is served from, including none.
##
## 3. IT RECURSES. The original scanned only the top level of the site root
##    and of each <lang>/ directory. Chapters do not live there -- they render
##    into <root>/chapters/ and <root>/<lang>/chapters/ -- so a non-recursive
##    scan touches the index pages and NOTHING ELSE, leaving all 49 chapters
##    with no switcher while still printing "done" and exiting 0. This script
##    walks the whole tree and refuses to exit 0 if it modified nothing below
##    the site root.
##
## Tree shape produced by build_all_chapters.sh's assembly step: the main
## language at the site root (<site_dir>/index.html, <site_dir>/chapters/*.html)
## and every other language one level down (<site_dir>/<lang>/index.<lang>.html,
## <site_dir>/<lang>/chapters/*.<lang>.html). A page's language is read from its
## first path segment, so the depth below that is not assumed.
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
## `canonical_rel` is a page's MAIN-LANGUAGE path relative to the site root,
## INCLUDING its directory: "chapters/basics.html", or "index.html". It must
## keep the directory. Reducing it to a basename was the original bug here:
## chapters render into html_outputs/chapters/, not the output root, so a
## basename-only scheme both misses those pages and, for a page nested at
## <lang>/chapters/, computes a link one directory too shallow.
target_rel_from_root <- function(lang, canonical_rel) {
  if (identical(lang, main_language)) {
    canonical_rel
  } else {
    file.path(lang, sub("\\.html$", sprintf(".%s.html", lang), canonical_rel))
  }
}

## href_for(): see departure (2) in the header comment. With no base_url the
## href is computed from the CURRENT page's own directory, so it is correct at
## any depth -- `chapters/basics.html` linking to French gives
## "../fr/chapters/basics.fr.html", and `fr/chapters/basics.fr.html` linking
## back to English gives "../../chapters/basics.html". Hard-coding ".." (the
## original) is only ever right for a page exactly one level down.
href_for <- function(doc_rel, target_lang, canonical_rel) {
  target <- target_rel_from_root(target_lang, canonical_rel)
  if (nzchar(base_url)) {
    paste0(base_url, "/", target)
  } else {
    as.character(fs::path_rel(target, start = dirname(doc_rel)))
  }
}

## add_dropdown_links(): mutate ONE HTML file in place, adding an <li><a>
## entry per target language. `targets` is a named list, target language
## code -> that page's main-language (infix-free) filename.
add_dropdown_links <- function(path, doc_rel, targets) {
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
    return(FALSE)
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
      href = href_for(doc_rel, lang, targets[[lang]]),
      id = sprintf("language-link-%s", lang)
    )
  }

  xml2::write_html(html, path)
  TRUE
}

## Enumerate EVERY page in the assembled tree, at any depth. recurse = TRUE
## is load-bearing: chapters render into <root>/chapters/ and
## <root>/<lang>/chapters/, so a non-recursive scan touches only the index
## pages and silently leaves all 49 chapters without a switcher -- while still
## printing "done" and exiting 0. babelquarto's own version recurses; dropping
## that was the bug.
##
## site_libs/ and Quarto's per-page *_files/ directories hold vendored JS/CSS,
## not book pages.
is_asset <- function(paths) {
  grepl("(^|/)site_libs/", paths) | grepl("_files/", paths)
}
all_docs <- fs::dir_ls(site_dir, glob = "*.html", recurse = TRUE)
all_docs <- all_docs[!is_asset(as.character(fs::path_rel(all_docs, start = site_dir)))]

## A page's language is its first path segment when that segment is a declared
## language directory; anything else is the main language. From that, derive
## the page's canonical (main-language) root-relative path, which is what every
## target path is built from.
lang_of <- function(doc_rel) {
  first <- strsplit(doc_rel, "/", fixed = TRUE)[[1]][1]
  if (first %in% language_codes) first else main_language
}
canonical_of <- function(doc_rel, lang) {
  if (identical(lang, main_language)) {
    doc_rel
  } else {
    sub(sprintf("^%s/", lang), "", sub(sprintf("\\.%s\\.html$", lang), ".html", doc_rel))
  }
}

n_main <- 0L
n_translated <- 0L
n_touched_chapters <- 0L
for (doc in all_docs) {
  doc_rel <- as.character(fs::path_rel(doc, start = site_dir))
  lang <- lang_of(doc_rel)
  canonical <- canonical_of(doc_rel, lang)
  others <- setdiff(c(main_language, language_codes), lang)

  ## Only offer a language whose version of THIS page actually exists -- a
  ## link to a page that was never rendered is worse than no link.
  present <- Filter(
    function(l) fs::file_exists(file.path(site_dir, target_rel_from_root(l, canonical))),
    others
  )
  if (length(present) == 0) next

  targets <- stats::setNames(as.list(rep(canonical, length(present))), present)
  changed <- add_dropdown_links(doc, doc_rel = doc_rel, targets = targets)
  if (identical(lang, main_language)) n_main <- n_main + 1L else n_translated <- n_translated + 1L
  ## Count on the CANONICAL path, not doc_rel. doc_rel has a "/" for any page
  ## in a language directory, including <lang>/index.<lang>.html -- which the
  ## broken non-recursive version DID reach, so counting doc_rel would let the
  ## guard pass on exactly the failure it exists to catch. The canonical path
  ## strips the language directory, so a "/" in it means a real subdirectory
  ## page: chapters/basics.html, never index.html.
  if (isTRUE(changed) && grepl("/", canonical, fixed = TRUE)) {
    n_touched_chapters <- n_touched_chapters + 1L
  }
}

## Guard against the exact failure this script just had: silently touching only
## the index pages. If nothing below the top level was modified, the tree shape
## is not what this script assumes and the site would deploy with no switcher
## on any chapter.
if (n_touched_chapters == 0L) {
  cat(
    "inject_language_links.R: no page below the site root was modified -- expected chapter pages under chapters/ and <lang>/chapters/. The assembled tree is not the shape this script assumes.\n",
    file = stderr()
  )
  quit(status = 1L)
}

cat(sprintf(
  "inject_language_links.R: done -- %d main-language page(s), %d translated page(s), %d of them below the site root, across %d language(s)\n",
  n_main,
  n_translated,
  n_touched_chapters,
  length(language_codes)
))
