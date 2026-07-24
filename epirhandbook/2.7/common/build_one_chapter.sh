#!/bin/bash
# build_one_chapter.sh -- render ONE handbook chapter to HTML from inside a
# per-chapter image. Installed in epirhandbook-common:2.7 and inherited by
# every chapter image (they are FROM common), so the render command is the
# same for all of them.
#
# The chapter's .qmd is PASSED IN as an argument, not baked into the image:
# the image is a package environment, content-agnostic. The book's
# navbar/sidebar/cross-links all come from _quarto.yml (part of the mounted
# book content), so a single-chapter render already produces a page that
# drops straight into the assembled site with correct navigation --
# PROVIDED the caller has already prepared a `_quarto.yml` that matches the
# language of the file being rendered.
#
# That preparation is the caller's job, not this script's. Rendering a
# translated `.qmd` (e.g. chapters/basics.fr.qmd) against the unmodified
# ENGLISH `_quarto.yml` fails SILENTLY: `quarto render` exits 0, but the
# HTML lands next to its source file, outside `html_outputs/`, titled with
# the bare filename, tagged `<html lang="en">`, with no sidebar navigation,
# and carrying its own duplicated copy of the site's JS/CSS assets. Exit
# status alone does not prove this render is correct. build_all_chapters.sh
# avoids this by running rewrite_lang_config.R over the mounted project
# BEFORE calling this script for any non-main language.
#
# THIS SCRIPT RENDERS ONE CHAPTER. It does not assemble the book, and it
# does not touch search.json: Quarto accumulates the project search index
# across separate per-file render invocations on its own, via the `.quarto/`
# state directory persisted on the mount, so there is nothing here to copy
# aside or merge. Assembling every chapter's output into one site, and
# adding the language-switcher links, is build_all_chapters.sh and
# inject_language_links.R (both in this same directory) -- see
# epirhandbook/2.7/README.md "Assembling the book".
#
# Usage (with the book content mounted at the working directory):
#   docker run --rm -v <book>:/book -w /book \
#     epirhandbook-<chapter>:2.7 build_one_chapter.sh chapters/<chapter>.qmd
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: build_one_chapter.sh <path/to/chapter.qmd>" >&2
  exit 2
fi
qmd="$1"
if [ ! -f "$qmd" ]; then
  echo "build_one_chapter.sh: file not found: $qmd (is the book content mounted at the working directory?)" >&2
  exit 2
fi

exec quarto render "$qmd"
