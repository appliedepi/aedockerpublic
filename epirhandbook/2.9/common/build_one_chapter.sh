#!/bin/bash
# build_one_chapter.sh -- render ONE handbook chapter to HTML from inside a
# group image or the monolith. Installed in epirhandbook-common:2.9 and
# inherited by the six group images and the monolith, which are all FROM
# common. The render command is the same for every one of them.
#
# The chapter's .qmd is PASSED IN as an argument, not baked into the image:
# the image is a package environment, content-agnostic. Every language is
# its own Quarto book project, at content/<lang>/ in the handbook checkout.
# That project's own _quarto.yaml carries the language, the title, the
# chapter list, the navbar, the sidebar and the cross-links. A
# single-chapter render therefore produces a page that drops straight into
# the assembled site, with correct navigation. That holds only while the
# caller runs this script with the language project as the WORKING
# DIRECTORY.
#
# That is the caller's job, not this script's. The output directory
# (html_outputs/), the sidebar and the cross-links are project-level
# settings, so quarto applies them only to a render that runs inside the
# project. Run from anywhere else, quarto renders the file as a standalone
# document. It exits 0, and the page lands beside its source with no book
# navigation and its own duplicated copy of the site's JS/CSS assets. The
# 2.8 line measured that failure on a translated .qmd rendered against the
# wrong project config, and the cause is the same one. Exit status alone
# does not prove this render is correct. build_all_chapters.sh avoids it by
# setting the container's working directory to /book/content/<lang>.
#
# THIS SCRIPT RENDERS ONE CHAPTER. It does not assemble the book, and it
# does not touch search.json: Quarto accumulates the project search index
# across separate per-file render invocations on its own, via the `.quarto/`
# state directory persisted on the mount, so there is nothing here to copy
# aside or merge. Assembling every language's output into one site, and
# adding the language-switcher links, is build_all_chapters.sh and
# inject_language_links.R (both in this same directory) -- see
# epirhandbook/2.9/README.md "Assembling the book".
#
# Usage (with the book content mounted, and the language project as the
# working directory):
#   docker run --rm -v <book>:/book -w /book/content/<lang> \
#     epirhandbook-<group>:2.9 build_one_chapter.sh <stem>.qmd
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
