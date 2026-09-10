#!/usr/bin/env Rscript
## inject_language_links.R -- the mandatory post-render pass: add the
## language-switcher dropdown (`<ul id="languages-links">`) to every HTML
## page in an ALREADY-ASSEMBLED output tree.
##
## WHY THIS EXISTS: rendering never produces the switcher. `quarto render`
## sees ONE language's project at a time and has no way to know which other
## languages exist. This script runs once, after every language has been
## rendered and assembled into one tree, and walks every emitted `.html`
## file to add it.
##
## THE TREE IT EXPECTS, which build_all_chapters.sh assembles: one directory
## per language at the site root, the main language included. A page is
## <site_dir>/en/basics.html or <site_dir>/fr/basics.html. Beside those sits
## <site_dir>/index.html, a redirect stub to the main language. A page's
## language is therefore its FIRST path segment, and the same page in
## another language is that same path with the first segment swapped. A page
## whose first segment is not a declared code is not a book page. The root
## stub is the only one today, and it is skipped.
##
## Three deliberate departures from quarto_runfile.R's add_link(), the
## vendored logic this ports:
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
##    case) that still yields a leading "/", i.e. a root-absolute path.
##    That breaks the moment the site is served from anything other than
##    its domain root (a deploy preview under a subpath, for instance).
##    This script takes `base_url` as an explicit, OPTIONAL argument:
##      - non-empty base_url  -> href = "<base_url>/<path-from-site-root>"
##        (root-relative to that base, same as the original when a real
##        site_url was supplied).
##      - empty base_url (the default) -> href is a TRUE relative path,
##        computed with fs::path_rel() from the CURRENT page's own directory,
##        so it is right at ANY depth. This resolves correctly under any base
##        path the site is served from, including none.
##
## 3. IT RECURSES. The original scanned only the top level of the site root
##    and of each <lang>/ directory. This script walks the whole tree and
##    refuses to exit 0 if it modified no chapter page.
##
## Usage:
##   Rscript inject_language_links.R <site_dir> <languages_yml> [<base_url>]
## <languages_yml> is the handbook's `languages.yml`: `main`, and
## `languages[]` with a `code` and a `label` each. That file is the one
## language list, read here for the switcher's order, codes and labels.

suppressPackageStartupMessages({
  library(xml2)
  library(yaml)
  library(fs)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2L || length(args) > 3L) {
  cat(
    "usage: inject_language_links.R <site_dir> <languages_yml> [<base_url>]\n",
    file = stderr()
  )
  quit(status = 2L)
}
site_dir <- normalizePath(args[[1]], mustWork = TRUE)
languages_yml <- args[[2]]
base_url <- if (length(args) == 3L) sub("/$", "", args[[3]]) else ""

if (!fs::file_exists(languages_yml)) {
  cat(
    sprintf(
      "inject_language_links.R: no languages.yml at '%s'\n",
      languages_yml
    ),
    file = stderr()
  )
  quit(status = 2L)
}
config <- yaml::yaml.load_file(languages_yml)

main_language <- config[["main"]]
entries <- config[["languages"]]
if (is.null(main_language) || length(entries) == 0L) {
  cat(
    sprintf(
      "inject_language_links.R: '%s' is missing 'main' or 'languages'\n",
      languages_yml
    ),
    file = stderr()
  )
  quit(status = 2L)
}

field_of <- function(entry, name) {
  value <- entry[[name]]
  if (is.null(value)) NA_character_ else as.character(value)
}
## File order IS the switcher order, so it is preserved verbatim.
language_codes <- vapply(entries, field_of, character(1), "code")
labels <- vapply(entries, field_of, character(1), "label")
names(labels) <- language_codes
if (anyNA(language_codes)) {
  cat(
    sprintf(
      "inject_language_links.R: every 'languages' entry in '%s' needs a 'code'\n",
      languages_yml
    ),
    file = stderr()
  )
  quit(status = 2L)
}
## The main language is not treated differently anywhere below: it has its
## own directory like every other language. It is checked here because a
## `main` outside the list means the site's root stub points at a language
## this tree does not hold.
if (!main_language %in% language_codes) {
  cat(
    sprintf(
      "inject_language_links.R: main language '%s' is not one of '%s''s declared codes (%s)\n",
      main_language,
      languages_yml,
      paste(language_codes, collapse = ", ")
    ),
    file = stderr()
  )
  quit(status = 2L)
}

## label_for(): the dropdown's display text for one language, from that
## language's own `label`. A code with no label costs one ugly menu entry,
## not the whole pass.
label_for <- function(lang) {
  label <- labels[[lang]]
  if (is.na(label)) sprintf("Version in %s", toupper(lang)) else label
}

## target_rel_from_root(): the emitted path of `lang`'s version of a page,
## relative to site_dir -- "fr/basics.html" for French. Every language has
## its own directory, so this is one expression for all of them. There is no
## special case for the main language, and no language infix in a filename.
## `canonical_rel` is the page's path MINUS its language segment:
## "basics.html", or "part/basics.html" for a page one directory deeper. It
## must keep any directory below the language: reducing it to a basename
## would compute a link one directory too shallow for a nested page.
target_rel_from_root <- function(lang, canonical_rel) {
  file.path(lang, canonical_rel)
}

## href_for(): see departure (2) in the header comment. With no base_url the
## href is computed from the CURRENT page's own directory, so it is correct at
## any depth -- `en/basics.html` linking to French gives
## "../fr/basics.html", and `en/part/basics.html` gives
## "../../fr/part/basics.html". Hard-coding ".." (the original) is only
## ever right for a page exactly one level down.
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
## code -> that page's canonical (language-free) path.
add_dropdown_links <- function(path, doc_rel, targets) {
  html <- xml2::read_html(path)

  sidebar <- xml2::xml_find_first(
    html,
    "//div[contains(@class,'sidebar-header')]"
  )
  if (inherits(sidebar, "xml_missing")) {
    ## A meta-refresh redirect stub has no sidebar at all. The alias stubs
    ## under new_pages/ never reach here, because is_alias_stub() drops them
    ## before this function runs. This guard catches any other sidebar-less
    ## page under a language folder. Skip one page rather than fail the whole
    ## pass.
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
## is load-bearing: a non-recursive scan finds nothing but the root stub,
## because every book page sits one level down under its language.
##
## site_libs/ and Quarto's per-page *_files/ directories hold vendored JS/CSS,
## not book pages.
is_asset <- function(paths) {
  grepl("(^|/)site_libs/", paths) | grepl("_files/", paths)
}

## new_pages/ holds the alias stubs that redirect the handbook's old URLs to
## their current pages. The contract keeps every file under new_pages/
## byte-identical after a run, so this exclusion tests the PATH and never the
## content. A content test is not enough. add_dropdown_links() skips a page
## that carries no sidebar, so it would rewrite any new_pages/ file that does
## carry one.
is_alias_stub <- function(paths) {
  grepl("(^|/)new_pages/", paths)
}

all_docs <- fs::dir_ls(site_dir, glob = "*.html", recurse = TRUE)
docs_rel <- as.character(fs::path_rel(all_docs, start = site_dir))
all_docs <- all_docs[!is_asset(docs_rel) & !is_alias_stub(docs_rel)]

## A page's language is its first path segment, when that segment is a
## declared code. Anything else is not a book page and is skipped: today
## that is the root redirect stub. The canonical path is the rest of the
## path, which is what every target path is built from.
lang_of <- function(doc_rel) {
  first <- strsplit(doc_rel, "/", fixed = TRUE)[[1]][1]
  if (first %in% language_codes) first else NA_character_
}
canonical_of <- function(doc_rel) {
  sub("^[^/]+/", "", doc_rel)
}

n_modified <- 0L
n_chapter_pages <- 0L
langs_touched <- character(0)
for (doc in all_docs) {
  doc_rel <- as.character(fs::path_rel(doc, start = site_dir))
  lang <- lang_of(doc_rel)
  if (is.na(lang)) {
    next
  }
  canonical <- canonical_of(doc_rel)
  others <- setdiff(language_codes, lang)

  ## Only offer a language whose version of THIS page actually exists -- a
  ## link to a page that was never rendered is worse than no link.
  present <- Filter(
    function(l) {
      fs::file_exists(file.path(site_dir, target_rel_from_root(l, canonical)))
    },
    others
  )
  if (length(present) == 0) {
    next
  }

  targets <- stats::setNames(as.list(rep(canonical, length(present))), present)
  changed <- add_dropdown_links(doc, doc_rel = doc_rel, targets = targets)
  ## Count only pages actually MODIFIED. Redirect stubs return FALSE from
  ## add_dropdown_links(), and reporting them as processed is exactly the kind
  ## of reassuring-but-wrong number this script already shipped once.
  if (isTRUE(changed)) {
    n_modified <- n_modified + 1L
    langs_touched <- union(langs_touched, lang)
    ## A chapter page is any modified page that is not a language's own
    ## index. Counting index pages here would let the guard below pass on a
    ## tree holding nothing but the eight landing pages.
    if (!identical(canonical, "index.html")) {
      n_chapter_pages <- n_chapter_pages + 1L
    }
  }
}

## Guard against the failure this script has had before: silently touching
## only the index pages, or nothing at all, and exiting 0 anyway. No chapter
## page modified means the assembled tree is not the shape this script
## assumes. The site would then deploy with no switcher on any chapter.
if (n_chapter_pages == 0L) {
  cat(
    "inject_language_links.R: no chapter page was modified -- expected pages under <lang>/ beside each language's index.html. The assembled tree is not the shape this script assumes.\n",
    file = stderr()
  )
  quit(status = 1L)
}

cat(sprintf(
  "inject_language_links.R: done -- %d page(s) modified, %d of them chapter pages, across %d of %d declared language(s)\n",
  n_modified,
  n_chapter_pages,
  length(langs_touched),
  length(language_codes)
))
