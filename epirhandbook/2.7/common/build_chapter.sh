#!/bin/bash
# build_chapter.sh -- render ONE handbook chapter to HTML from inside a
# per-chapter image. Installed in epirhandbook-common:2.7 and inherited by
# every chapter image (they are FROM common), so the render command is the
# same for all of them.
#
# The chapter's .qmd is PASSED IN as an argument, not baked into the image:
# the image is a package environment, content-agnostic. The book's
# navbar/sidebar/cross-links all come from _quarto.yml (part of the mounted
# book content), so a single-chapter render already produces a page that drops
# straight into the assembled site with correct navigation.
#
# THIS SCRIPT RENDERS ONE CHAPTER. It does NOT assemble the book. Collecting
# every chapter's output into one site, and merging each chapter's per-render
# search.json into ONE global search index (a single-chapter render only
# indexes its own page), is the epirhandbook WEBSITE repo's CI -- a separate,
# future concern. See epirhandbook/2.7/README.md "Assembling the book".
#
# Usage (with the book content mounted at the working directory):
#   docker run --rm -v <book>:/book -w /book \
#     epirhandbook-<chapter>:2.7 build_chapter.sh new_pages/<chapter>.qmd
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: build_chapter.sh <path/to/chapter.qmd>" >&2
  exit 2
fi
qmd="$1"
if [ ! -f "$qmd" ]; then
  echo "build_chapter.sh: file not found: $qmd (is the book content mounted at the working directory?)" >&2
  exit 2
fi

exec quarto render "$qmd"
