#!/bin/bash
# build_one_chapter.sh: render ONE handbook chapter to HTML inside a group
# image or the monolith. It is installed in epirhandbook-common:2.9. The six
# group images and the monolith are all FROM common, so they inherit it. The
# render command is the same in each of them.
#
# The caller PASSES the .qmd of the chapter as an argument. The image does
# not hold it: the image is a package environment and holds no content. Each
# language is its own Quarto book project, at content/<lang>/ in the
# handbook checkout. The _quarto.yaml of that project gives the language, the
# title, the chapter list, the navbar, the sidebar and the cross-links. Thus
# a render of one chapter makes a page that fits into the assembled site,
# with correct navigation. This is true only when the caller runs this
# script with the language project as the WORKING DIRECTORY.
#
# The caller MUST set that working directory. This script does not. The
# output directory (html_outputs/), the sidebar and the cross-links are
# project settings. Quarto applies them only to a render that runs inside the
# project. From any other directory, Quarto renders the file as a standalone
# document. It exits 0, and the page goes next to its source. That page has
# no book navigation, and it has its own copy of the JS/CSS assets of the
# site. The 2.8 line
# measured this failure on a translated .qmd that rendered against the wrong
# project config, from the same cause. Exit status alone does not show that
# the render is correct. build_all_chapters.sh prevents the failure: it sets
# the working directory of the container to /book/content/<lang>.
#
# THIS SCRIPT RENDERS ONE CHAPTER. It does not assemble the book, and it
# does not touch search.json. Quarto adds each separate render to the
# project search index itself, through the `.quarto/` state directory that
# stays on the mount. Thus there is nothing here to copy or merge.
# build_all_chapters.sh and inject_language_links.R, both in this directory,
# assemble the output of every language into one site and add the
# language-switcher links. See "Assembling the book" in
# epirhandbook/README.md.
#
# Usage, with the book content mounted and the language project as the
# working directory. build_all_chapters.sh uses these flags:
#   docker run --rm --network none \
#     -e R_PROFILE_USER=/usr/local/lib/ehb/warnings_to_log.R \
#     -v <book>:/book -w /book/content/<lang> \
#     epirhandbook-<group>:2.9 build_one_chapter.sh <stem>.qmd
# A render by hand MAY leave out --network none and R_PROFILE_USER. The
# header of warnings_to_log.R says what the profile writes to the log.
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
# R ignores an R_PROFILE_USER that names a missing file, and gives no
# message. The render would then log no warnings, and nothing would show it.
if [ -n "${R_PROFILE_USER:-}" ] && [ ! -r "$R_PROFILE_USER" ]; then
  echo "build_one_chapter.sh: R_PROFILE_USER is '$R_PROFILE_USER', and this image holds no readable file there" >&2
  exit 2
fi

exec quarto render "$qmd"
