#!/usr/bin/env Rscript
## inject_language_links.R: the required pass after the render. It adds the
## language-switcher dropdown (`<ul id="languages-links">`) to every HTML
## page in an output tree that is ALREADY ASSEMBLED.
##
## WHY THIS EXISTS: the render does not make the switcher. `quarto render`
## sees the project of ONE language at a time, and cannot know which other
## languages exist. This script runs once, after every language is rendered
## and assembled into one tree. It reads every `.html` file and adds the
## switcher.
##
## THE TREE IT EXPECTS, which build_all_chapters.sh assembles: one directory
## for each language at the site root, the main language included. A page is
## <site_dir>/en/basics.html or <site_dir>/fr/basics.html. Next to those is
## <site_dir>/index.html, a redirect stub to the main language. Thus the
## language of a page is its FIRST path segment. The same page in another
## language has the same path with a different first segment. A page whose
## first segment is not a declared code is not a book page. Today the root
## stub is the only such page, and the script skips it.
##
## This script ports add_link() from quarto_runfile.R, vendored code. It
## differs from add_link() in three ways:
##
## 1. THE <li> BUG IS FIXED. The original makes `<a>` a direct child of the
##    `<ul>`. It then tries to wrap the `<a>` in `<li>` with
##    `xml_add_parent(xml_find_first(html, "a[id='...']"), "li")`. That
##    XPath has no leading `//`. It also uses `id='...'` as a test for an
##    ELEMENT CHILD, not `@id='...'`, a test for an attribute. Thus it cannot
##    match the anchor that the original just made. xml_add_parent() finds
##    nothing to wrap and gives no error, and the `<li>` is never added.
##    Browsers accept a bare `<a>` in a `<ul>`, but it is not valid list
##    markup. This script makes the `<li>` first and adds the `<a>` IN it,
##    so the output is always `<ul><li><a>...</a></li></ul>`.
##
## 2. HREFS ARE NEVER ROOT-ABSOLUTE. The original makes every href as
##    `paste0(site_url, "/", path)`. When `site_url` is empty, the usual
##    case, the href still starts with "/", so it is a root-absolute path.
##    That path fails when the server puts the site anywhere other than the
##    root of its domain, for example a deploy preview under a subpath.
##    This script takes `base_url` as an OPTIONAL argument:
##      - non-empty base_url  -> href = "<base_url>/<path-from-site-root>".
##        The href is relative to that base, as in the original when the
##        caller gave a real site_url.
##      - empty base_url (the default) -> href is a TRUE relative path. The
##        script computes it with fs::path_rel() from the directory of the
##        CURRENT page, so it is correct at ANY depth. It resolves correctly
##        under any base path of the site, and with no base path.
##
## 3. IT RECURSES. The original read only the top level of the site root
##    and of each <lang>/ directory. This script reads the whole tree. It
##    exits with an error if it changed no chapter page.
##
## Usage:
##   Rscript inject_language_links.R <site_dir> <languages_yml> [<base_url>]
## <languages_yml> is the `languages.yml` of the handbook: `main`, and
## `languages[]`, each with a `code` and a `label`. That file is the one
## language list. The script reads the order, the codes and the labels of
## the switcher from it.

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
## The yaml package reads an unquoted yes, no, on, off, y, n, true or false as
## a logical. These handlers keep each one as its text, so the Norwegian code
## `no` stays "no" instead of becoming "FALSE".
config <- yaml::yaml.load_file(
  languages_yml,
  handlers = list("bool#yes" = function(x) x, "bool#no" = function(x) x)
)

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
## The order in the file IS the switcher order, so the script keeps it.
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
## Below, the main language has no special case: it has its own directory,
## as every other language does. The script checks it here for one reason.
## A `main` outside the list means that the root stub of the site points at
## a language that this tree does not hold.
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

## label_for(): the dropdown text for one language, from the `label` of that
## language. A code with no label gives one poor menu entry, and the pass
## does not fail.
label_for <- function(lang) {
  label <- labels[[lang]]
  if (is.na(label)) sprintf("Version in %s", toupper(lang)) else label
}

## target_rel_from_root(): the output path of the `lang` version of a page,
## relative to site_dir. For French, it is "fr/basics.html". Every language
## has its own directory, so one expression serves all of them. There is no
## special case for the main language, and no language code in a filename.
## `canonical_rel` is the path of the page WITHOUT its language segment:
## "basics.html", or "part/basics.html" for a page one directory deeper. It
## MUST keep every directory below the language. With only the basename, the
## link for a nested page would be one directory too shallow.
target_rel_from_root <- function(lang, canonical_rel) {
  file.path(lang, canonical_rel)
}

## href_for(): see difference (2) in the header comment. With no base_url,
## the href comes from the directory of the CURRENT page, so it is correct at
## any depth. A link from `en/basics.html` to French is "../fr/basics.html".
## From `en/part/basics.html` it is "../../fr/part/basics.html". The
## original hard-codes "..", which is correct only for a page one level
## down.
href_for <- function(doc_rel, target_lang, canonical_rel) {
  target <- target_rel_from_root(target_lang, canonical_rel)
  if (nzchar(base_url)) {
    paste0(base_url, "/", target)
  } else {
    as.character(fs::path_rel(target, start = dirname(doc_rel)))
  }
}

## add_dropdown_links(): change ONE HTML file in place. It adds one <li><a>
## entry for each target language. `targets` is a named list: target
## language code -> the canonical path of the page, with no language.
add_dropdown_links <- function(path, doc_rel, targets) {
  html <- xml2::read_html(path)

  sidebar <- xml2::xml_find_first(
    html,
    "//div[contains(@class,'sidebar-header')]"
  )
  if (inherits(sidebar, "xml_missing")) {
    ## A meta-refresh redirect stub has no sidebar. The alias stubs under
    ## new_pages/ do not get here, because is_alias_stub() removes them
    ## before this function runs. This guard finds any other page with no
    ## sidebar under a language directory. It skips that page, and the pass
    ## does not fail.
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

## List EVERY page in the assembled tree, at any depth. recurse = TRUE is
## necessary. Without it, the scan finds only the root stub, because every
## book page is one level down, under its language.
##
## site_libs/ and the *_files/ directory that Quarto makes for each page hold
## vendored JS/CSS. They are not book pages.
is_asset <- function(paths) {
  grepl("(^|/)site_libs/", paths) | grepl("_files/", paths)
}

## new_pages/ holds the alias stubs that redirect the old URLs of the
## handbook to their current pages. The contract says that a run MUST NOT
## change any byte of a file under new_pages/. Thus this exclusion tests the
## PATH, not the content. A content test is not sufficient.
## add_dropdown_links() skips a page that has no sidebar, so it would change
## any new_pages/ file that has one.
is_alias_stub <- function(paths) {
  grepl("(^|/)new_pages/", paths)
}

all_docs <- fs::dir_ls(site_dir, glob = "*.html", recurse = TRUE)
docs_rel <- as.character(fs::path_rel(all_docs, start = site_dir))
all_docs <- all_docs[!is_asset(docs_rel) & !is_alias_stub(docs_rel)]

## The language of a page is its first path segment, when that segment is a
## declared code. Any other page is not a book page, and the script skips it.
## Today that is the root redirect stub. The canonical path is the rest of
## the path. The script makes every target path from it.
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

  ## Offer only a language that has a version of THIS page. A link to a page
  ## that was not rendered is worse than no link.
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
  ## Count only pages that the script CHANGED. Redirect stubs return FALSE
  ## from add_dropdown_links(). An earlier version of this script counted
  ## them as processed, and that count was wrong.
  if (isTRUE(changed)) {
    n_modified <- n_modified + 1L
    langs_touched <- union(langs_touched, lang)
    ## A chapter page is any changed page that is not the index of a
    ## language. If this count included index pages, the guard below would
    ## pass on a tree that holds only the eight landing pages.
    if (!identical(canonical, "index.html")) {
      n_chapter_pages <- n_chapter_pages + 1L
    }
  }
}

## This guard stops a failure that this script had before: it changed only
## the index pages, or no page, and still exited 0. If no chapter page
## changed, the assembled tree does not have the expected shape. The site
## would then deploy with no switcher on any chapter.
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
