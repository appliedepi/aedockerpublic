#!/bin/bash
# build_all_chapters.sh -- render every chapter, in every language, and
# assemble one output tree.
#
# THIS RUNS ON THE CI RUNNER, NOT INSIDE A CONTAINER. It starts one
# container per chapter render (docker run ... build_one_chapter.sh ...),
# so running it inside a container itself would need docker-in-docker. It
# is nonetheless STORED in epirhandbook-common:2.7 (this file lives at
# common/build_all_chapters.sh and is COPYed onto PATH by common/Dockerfile,
# exactly like build_one_chapter.sh), so there is a single source of truth
# for it. The CI runner extracts it before running it:
#   docker run --rm <common-image> cat /usr/local/bin/build_all_chapters.sh > build_all.sh
#
# WHAT THIS REPLACES: the whole book used to be rendered by one call
# (quarto_runfile.R, a vendored copy of babelquarto's render() logic). This
# script instead renders one .qmd at a time, each in its own pinned
# per-chapter image, so a chapter can be pinned back to an older image
# (epirhandbook-basics:2.6, say) independently of the rest of the book.
#
# INPUTS: the handbook checkout (containing `_quarto.yml` and the
# chapter->image manifest, `docker-images.yml`, at its root) and the
# registry prefix images are pulled from.
#
# WHY NOT A LANGUAGE LIST ARGUMENT: `_quarto.yml`'s
# `babelquarto.mainlanguage` / `babelquarto.languages` are the single
# source of truth for which languages ship. Accepting a language list here
# too would be a second, driftable source of the same fact.
#
# THE MANIFEST (docker-images.yml, at the HANDBOOK repo's root -- not this
# repo): one row per chapter, covering every language of that chapter.
#   registry: ghcr.io/appliedepi/aedockerpublic
#   chapters:
#     - stem: time_series
#       image: epirhandbook-time_series:2.7
#     - stem: basics
#       image: epirhandbook-basics:2.6      # deliberately pinned back
# A book chapter with no manifest row is a MISSING ENTRY, not something to
# render with a guessed default -- see check_manifest_covers_book() below.
#
# THE TWO HARD CONSTRAINTS THIS SCRIPT EXISTS TO HONOUR (both measured, not
# assumed -- see the brief this script was written from):
#   1. Renders for a given language MUST share one persistent workspace and
#      run SEQUENTIALLY. Quarto accumulates the project search index
#      (search.json) across separate per-file render invocations via the
#      `.quarto/` state directory on the shared mount; parallel renders
#      within one language would race on it. Different LANGUAGES use
#      separate workspaces, so they have nothing to race on and MAY be
#      processed in parallel with each other -- see the `for lang in
#      "${ALL_LANGS[@]}"` loop below, which deliberately does NOT do so.
#   2. EVERY CHAPTER MUST BE RENDERED TWICE, in the same workspace. A
#      chapter rendered before its cross-reference target has registered
#      in `.quarto/xref` falls back to a same-page anchor that does not
#      exist on that page (a proven, measured dead link -- 3 of them, in
#      one small spike). A second full pass, after every chapter has
#      registered once, resolves them: re-running the same renders a second
#      time took the dead-link count from 3 to 0 and reproduced the
#      whole-book reference byte-for-byte. Do not remove pass 2 -- it looks
#      redundant and it is not; removing it produces dead links silently,
#      not a build error.
#
# FAIL LOUDLY: a chapter that fails to render fails this build, immediately,
# naming the chapter, the language, and the pass. Rendering itself is not
# enough to trust, either -- see finding 1 in this script's own header
# history: 24 renders can exit 0 while producing unusable output. See
# validate_language() below for the checks that catch that.
set -euo pipefail

fail() {
  echo "::error::build_all_chapters.sh: $*" >&2
  exit 1
}

usage() {
  echo "usage: build_all_chapters.sh [--only-lang <code>] [--no-inject] <handbook_dir> <registry_prefix> [<output_dir>]" >&2
  echo "  --only-lang <code>  render just this ONE language, which must already be declared in" >&2
  echo "                      _quarto.yml. Its site lands at the ROOT of <output_dir>, with no" >&2
  echo "                      <lang>/ nesting. Use one leg per language in a CI matrix." >&2
  echo "  --no-inject         skip the language-switcher pass. REQUIRED when languages are split" >&2
  echo "                      across legs: the injector is not idempotent, so it must run exactly" >&2
  echo "                      once, over the fully assembled site." >&2
  echo "  <handbook_dir>      checkout of the handbook repo (has _quarto.yml + docker-images.yml)" >&2
  echo "  <registry_prefix>   e.g. ghcr.io/appliedepi/aedockerpublic -- images are '<registry_prefix>/<image>'" >&2
  echo "  <output_dir>        where the assembled site is written (default: ./html_outputs)" >&2
}

# --- book-level tooling always runs against THIS common image, never a
# --- chapter's (possibly pinned-back) one: the config rewrite and the
# --- language-link injection are per-BOOK steps, not per-chapter ones, so
# --- which chapter image happens to also carry rewrite_lang_config.R /
# --- inject_language_links.R is irrelevant. This script itself lives in
# --- epirhandbook/2.7, so "2.7" is the correct common tag for it to use.
COMMON_TAG="2.7"

# --- arg parsing -------------------------------------------------------------
# Two optional flags, both there so a CI matrix can put ONE language in each
# leg. Without them a caller has to render every language in every leg and
# throw most of it away, and has to strip this script's own switcher markup
# back out of the HTML afterwards -- both of which were real workarounds in
# the first version of the handbook workflow.
ONLY_LANG=""
DO_INJECT=1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --only-lang)
      [ "$#" -ge 2 ] || { echo "--only-lang needs a language code" >&2; usage; exit 2; }
      ONLY_LANG="$2"; shift 2 ;;
    --no-inject) DO_INJECT=0; shift ;;
    --) shift; break ;;
    -*) echo "unknown option: $1" >&2; usage; exit 2 ;;
    *) break ;;
  esac
done

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  usage
  exit 2
fi
HANDBOOK_DIR_ARG="$1"
REGISTRY_PREFIX="$2"
OUTPUT_DIR="${3:-$PWD/html_outputs}"

[ -d "$HANDBOOK_DIR_ARG" ] || fail "no such directory: $HANDBOOK_DIR_ARG"
HANDBOOK_DIR="$(cd "$HANDBOOK_DIR_ARG" && pwd)"
[ -f "$HANDBOOK_DIR/_quarto.yml" ] || fail "no _quarto.yml in $HANDBOOK_DIR"
[ -f "$HANDBOOK_DIR/docker-images.yml" ] || fail "no docker-images.yml in $HANDBOOK_DIR"
[ -n "$REGISTRY_PREFIX" ] || fail "registry prefix (arg 2) must not be empty"

COMMON_IMAGE="$REGISTRY_PREFIX/epirhandbook-common:$COMMON_TAG"

# --- read the language list from _quarto.yml (the single source of truth) --
# Uses real PyYAML, matching this repo's own established rule for reading
# YAML (see .github/scripts/requirements.txt's header): no hand-rolled
# parser, ever, for the same reasons that file documents at length.
read_languages() {
  python3 - "$HANDBOOK_DIR/_quarto.yml" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as fh:
    cfg = yaml.safe_load(fh)
bq = cfg.get("babelquarto") or {}
main = bq.get("mainlanguage")
langs = bq.get("languages") or []
if not main:
    sys.exit("::error::build_all_chapters.sh: babelquarto.mainlanguage missing from " + sys.argv[1])
if not langs:
    sys.exit("::error::build_all_chapters.sh: babelquarto.languages missing/empty in " + sys.argv[1])
print(main)
print(" ".join(langs))
PY
}

lang_info_file="$(mktemp)"
if ! read_languages > "$lang_info_file"; then
  cat "$lang_info_file" >&2
  rm -f "$lang_info_file"
  fail "could not read the language list from $HANDBOOK_DIR/_quarto.yml"
fi
MAIN_LANG="$(sed -n '1p' "$lang_info_file")"
read -r -a OTHER_LANGS <<< "$(sed -n '2p' "$lang_info_file")"
rm -f "$lang_info_file"
ALL_LANGS=("$MAIN_LANG" "${OTHER_LANGS[@]}")

# --only-lang narrows the run to ONE of the languages _quarto.yml declares.
# It never invents a language: the code must already be in that list, so this
# cannot be used to render something the book does not ship.
#
# LAYOUT NOTE, load-bearing for the caller: under --only-lang the OUTPUT_DIR
# holds that language's site AT ITS ROOT, with no <lang>/ nesting -- there is
# nothing to nest it under, because no other language was rendered. A CI leg
# uploads that directory as-is; whoever assembles the legs decides where each
# one lands. Without the flag, the layout is unchanged: main language at the
# root, every other language under <lang>/.
# ASSEMBLE_ROOT_LANG is the language that ends up at OUTPUT_DIR's root. It is
# NOT the same thing as MAIN_LANG, and conflating the two is a silent-failure
# trap: MAIN_LANG decides whether a workspace gets rewrite_lang_config.R run
# over it (prepare_workspace) and whether a chapter path carries a .<lang>
# infix (chapter_path_for_lang), so it must stay the book's REAL main language
# even when --only-lang fr puts French at the root. Setting MAIN_LANG=fr here
# would skip French's config rewrite entirely -- and that failure exits 0.
ASSEMBLE_ROOT_LANG="$MAIN_LANG"
if [ -n "$ONLY_LANG" ]; then
  found=0
  for l in "${ALL_LANGS[@]}"; do [ "$l" = "$ONLY_LANG" ] && found=1; done
  [ "$found" -eq 1 ] || fail "--only-lang '$ONLY_LANG' is not one of _quarto.yml's babelquarto languages (${ALL_LANGS[*]})"
  ALL_LANGS=("$ONLY_LANG")
  OTHER_LANGS=()
  ASSEMBLE_ROOT_LANG="$ONLY_LANG"
  echo "build_all_chapters.sh: --only-lang $ONLY_LANG -- rendering that language alone, output at the root of $OUTPUT_DIR"
fi

# --- read the chapter->image manifest ---------------------------------------
# docker-images.yml lives at the HANDBOOK repo's root (a separate repo from
# this one) -- read via the checkout passed in as $HANDBOOK_DIR.
read_manifest() {
  python3 - "$HANDBOOK_DIR/docker-images.yml" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as fh:
    cfg = yaml.safe_load(fh)
chapters = cfg.get("chapters") or []
if not chapters:
    sys.exit("::error::build_all_chapters.sh: no 'chapters' entries in " + sys.argv[1])
for row in chapters:
    stem = row.get("stem")
    image = row.get("image")
    if not stem or not image:
        sys.exit("::error::build_all_chapters.sh: manifest row missing 'stem' or 'image': " + repr(row))
    print(f"{stem}\t{image}")
PY
}

MANIFEST_FILE="$(mktemp)"
if ! read_manifest > "$MANIFEST_FILE"; then
  cat "$MANIFEST_FILE" >&2
  rm -f "$MANIFEST_FILE"
  fail "could not read the chapter manifest from $HANDBOOK_DIR/docker-images.yml"
fi

# --- do not silently skip a chapter with no manifest entry ------------------
# Every main-language chapter file that actually exists in the book must
# have a manifest row; a chapter the manifest never mentions is a MISSING
# ENTRY (someone added a chapter and forgot the manifest), not a chapter to
# quietly skip.
# The book is what _quarto.yml DECLARES, not what happens to be on disk.
# chapters/ also holds obsolete drafts and category stubs that no longer
# appear in book.chapters (plot_continuous, modeling, relational_databases,
# the cat_* files, and any chapter deliberately commented out). Globbing the
# directory instead of reading the config demands a manifest row for every one
# of them and fails the build outright -- which is exactly what it did.
#
# Checked in BOTH directions, because each catches a different mistake:
# a declared chapter with no row means someone added a chapter and forgot the
# manifest; a row for an undeclared chapter means the manifest would render an
# orphan page that is in no book, or name an image that need not exist.
check_manifest_covers_book() {
  local declared missing extra
  declared="$(python3 - "$HANDBOOK_DIR/_quarto.yml" <<'PY'
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1]))
paths = []
def walk(node):
    if isinstance(node, str) and node.endswith(".qmd"):
        paths.append(node)
    elif isinstance(node, list):
        for item in node: walk(item)
    elif isinstance(node, dict):
        for value in node.values(): walk(value)
walk(cfg["book"]["chapters"])
for stem in sorted({p.split("/")[-1][:-4] for p in paths}):
    print(stem)
PY
)" || fail "could not read book.chapters from $HANDBOOK_DIR/_quarto.yml"

  missing=""
  while IFS= read -r stem; do
    [ -n "$stem" ] || continue
    grep -q -P "^${stem}\t" "$MANIFEST_FILE" || missing="$missing $stem"
  done <<< "$declared"
  [ -z "$missing" ] || fail "chapter(s) declared in _quarto.yml with no docker-images.yml entry:$missing -- add a manifest row for each"

  extra=""
  while IFS=$'\t' read -r stem _; do
    grep -q -x -F "$stem" <<< "$declared" || extra="$extra $stem"
  done < "$MANIFEST_FILE"
  [ -z "$extra" ] || fail "docker-images.yml row(s) for chapter(s) _quarto.yml does not declare:$extra -- remove them, or add the chapter to book.chapters"
}
check_manifest_covers_book

# --- stem -> source .qmd path, for a given language -------------------------
# Fixed fact of the handbook repo's layout (not derived from _quarto.yml):
# chapters live at chapters/<stem>.qmd, translations at
# chapters/<stem>.<lang>.qmd; the one exception is "index", which sits at
# the project root as index.qmd / index.<lang>.qmd. For the MAIN language
# specifically, the plain (infix-free) path is always correct: main-language
# workspaces are never passed through rewrite_lang_config.R (see
# prepare_workspace() below), so their files never gain a language infix.
chapter_path_for_lang() {
  local stem="$1" lang="$2"
  if [ "$stem" = "index" ]; then
    if [ "$lang" = "$MAIN_LANG" ]; then printf 'index.qmd'; else printf 'index.%s.qmd' "$lang"; fi
  else
    if [ "$lang" = "$MAIN_LANG" ]; then printf 'chapters/%s.qmd' "$stem"; else printf 'chapters/%s.%s.qmd' "$stem" "$lang"; fi
  fi
}

WORK_ROOT="$(mktemp -d)"
echo "build_all_chapters.sh: workspace root: $WORK_ROOT (not auto-cleaned -- inspect on failure)"

# --- one fresh workspace per language, ALWAYS from the pristine checkout ----
# Finding 7 (not idempotent): rewrite_lang_config.R must never run twice on
# the same tree, and must never run on a tree another language's run has
# already touched. Sourcing every workspace from $HANDBOOK_DIR itself, every
# time, is what guarantees that -- never from $WORK_ROOT/<some-other-lang>.
prepare_workspace() {
  local lang="$1" ws="$WORK_ROOT/$lang"
  rm -rf "$ws"
  mkdir -p "$ws"
  cp -a "$HANDBOOK_DIR"/. "$ws"/

  if [ "$lang" != "$MAIN_LANG" ]; then
    echo "build_all_chapters.sh: rewriting _quarto.yml for lang=$lang"
    if ! docker run --rm -v "$ws:/book" -w /book "$COMMON_IMAGE" \
        Rscript /usr/local/bin/rewrite_lang_config.R /book "$lang"; then
      fail "rewrite_lang_config.R failed for lang=$lang in $ws"
    fi
  fi
}

# --- render every manifest chapter once, for one language ONE pass ---------
# SEQUENTIAL BY CONSTRUCTION: this is a plain bash `while read` loop with no
# backgrounding (`&`), so chapter N+1 never starts before chapter N's
# `docker run` has exited. That is what honours finding 3 (search.json
# would race under parallel renders within a language).
render_pass() {
  local lang="$1" ws="$2" pass="$3"
  local stem image qmd image_ref
  while IFS=$'\t' read -r stem image; do
    qmd="$(chapter_path_for_lang "$stem" "$lang")"
    if [ ! -f "$ws/$qmd" ]; then
      fail "lang=$lang pass=$pass: expected source '$ws/$qmd' for chapter '$stem' does not exist"
    fi
    image_ref="$REGISTRY_PREFIX/$image"
    echo "build_all_chapters.sh: lang=$lang pass=$pass: rendering $qmd with $image_ref"
    if ! docker run --rm -v "$ws:/book" -w /book "$image_ref" build_one_chapter.sh "$qmd"; then
      fail "lang=$lang pass=$pass: chapter '$stem' failed to render '$qmd' using '$image_ref'"
    fi
  done < "$MANIFEST_FILE"
}

# --- validate before assembling: exit 0 proves nothing here -----------------
# Finding 1 measured 24 renders exiting 0 while producing unusable output.
# These three checks are what a bare exit-code check would have missed, in
# increasing order of how much they'd have caught: (a) the file was never
# produced at all; (b) it was produced but never indexed for search; (c) it
# was produced, indexed, AND still contains a dead same-page link -- this
# last one is what would have caught finding 6 (the dead-link regression),
# so it is the important one.
validate_language() {
  local lang="$1" ws="$2"
  local outdir="$ws/html_outputs"
  local search="$outdir/search.json"
  local stem image qmd html frag f

  [ -d "$outdir" ] || fail "lang=$lang: no '$outdir' -- nothing was rendered"
  [ -f "$search" ] || fail "lang=$lang: '$search' is missing -- no search index was produced"

  # Quarto mirrors the SOURCE subdirectory into the output: chapters/x.qmd
  # renders to html_outputs/chapters/x.html, not html_outputs/x.html. Keep the
  # whole relative path -- basename'ing it here would look for a file that
  # never exists and fail every chapter. `index.qmd` has no subdirectory, so
  # the same expression gives html_outputs/index.html for it.
  # search.json's href is that same relative path, so it is compared verbatim
  # rather than by basename (a basename match would also accept a DIFFERENT
  # chapter of the same name in another directory).
  while IFS=$'\t' read -r stem image; do
    qmd="$(chapter_path_for_lang "$stem" "$lang")"
    rel="${qmd%.qmd}.html"
    html="$outdir/$rel"
    [ -f "$html" ] || fail "lang=$lang: expected output '$html' (chapter '$stem', from '$qmd' via '$image') was never produced"
    grep -F -q "\"$rel\"" "$search" \
      || fail "lang=$lang: '$search' does not reference '$rel' (chapter '$stem')"
  done < "$MANIFEST_FILE"

  # Dead-same-page-link check: every href="#frag" must have a matching
  # id="frag" IN THE SAME FILE. href="#" (an empty fragment) is excluded
  # deliberately -- it is a JS-hook placeholder used by dropdown/toggle
  # controls in the page template, never a same-page anchor, and same-page
  # anchors are never empty strings.
  # Dead same-page fragments are REPORTED, never fatal. It is tempting to fail
  # the build on them -- that is the exact symptom of the cross-reference bug
  # the second render pass exists to fix. It does not work as a gate, and this
  # was measured, not assumed: the whole-book reference render of the real
  # 49-chapter book (the one that reproduces the live site) contains 106 dead
  # fragments of its own after percent-decoding, and 4552 before it. They are
  # pre-existing content bugs -- `#gis` 15 times, `#contact_us` 7 -- not render
  # faults. A gate here would fail every build forever, and a numeric threshold
  # would be arbitrary.
  #
  # So: count them, print the worst, move on. What actually guards the
  # cross-reference bug is the second render pass itself, plus the two checks
  # above, which are exact and do fail the build.
  #
  # Percent-decoding matters: an href fragment is URL-encoded
  # (`#r%C3%A9visions-majeures`) while the matching `id=` is not, so a literal
  # comparison reports ~40x more "dead" links than really are.
  local dead
  dead="$(python3 - "$outdir" <<'PY'
import re, glob, os, sys, urllib.parse, collections
root = sys.argv[1]
files = [f for f in glob.glob(root + "/**/*.html", recursive=True) if "/site_libs/" not in f]
n = 0
worst = collections.Counter()
for path in files:
    text = open(path, encoding="utf-8", errors="replace").read()
    ids = set(re.findall(r'id="([^"]*)"', text))
    for frag in set(re.findall(r'href="#([^"]*)"', text)):
        if frag and frag not in ids and urllib.parse.unquote(frag) not in ids:
            n += 1
            worst[urllib.parse.unquote(frag)] += 1
print(n, " ".join(f"#{k}x{v}" for k, v in worst.most_common(5)))
PY
)" || dead="?"
  echo "build_all_chapters.sh: lang=$lang: dead same-page fragments: $dead"
}

# This loop is a plain, SEQUENTIAL `for`, one language after another, even
# though languages use independent workspaces and COULD safely run in
# parallel (see constraint 1 above): backgrounding it correctly means
# capturing each subshell's exit status without losing it (a masked
# background failure is exactly the "fail loudly" hazard this script exists
# to avoid), and that is untested complexity this change does not need.
# Nothing here stops a future version from backgrounding it.
for lang in "${ALL_LANGS[@]}"; do
  ws="$WORK_ROOT/$lang"
  prepare_workspace "$lang"
  # Pass 1: populates .quarto/xref with every chapter's targets.
  render_pass "$lang" "$ws" 1
  # Pass 2 (finding 6 -- NOT redundant, see header comment): re-renders every
  # chapter now that every OTHER chapter's cross-reference targets are known,
  # which is what resolves them instead of silently falling back to a
  # same-page fragment.
  render_pass "$lang" "$ws" 2
  validate_language "$lang" "$ws"
done

# --- assemble one output tree -----------------------------------------------
# The main language's html_outputs/ becomes the ROOT: English at
# html_outputs/index.html, NOT html_outputs/en/index.html, because both the
# switcher's hrefs and the reference (whole-book) layout expect English at
# the site root. Each other language is copied to html_outputs/<lang>/.
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
# ASSEMBLE_ROOT_LANG, not MAIN_LANG: under --only-lang fr there is no English
# workspace to copy from, and French is what goes at the root.
cp -a "$WORK_ROOT/$ASSEMBLE_ROOT_LANG/html_outputs"/. "$OUTPUT_DIR"/
if [ "${#OTHER_LANGS[@]}" -gt 0 ]; then
  for lang in "${OTHER_LANGS[@]}"; do
    mkdir -p "$OUTPUT_DIR/$lang"
    cp -a "$WORK_ROOT/$lang/html_outputs"/. "$OUTPUT_DIR/$lang"/
  done
fi
echo "build_all_chapters.sh: assembled $OUTPUT_DIR (root=$ASSEMBLE_ROOT_LANG, nested=${OTHER_LANGS[*]:-none})"

# --- the language-switcher post-pass ----------------------------------------
# Runs once, over the FULLY ASSEMBLED tree, in the common image (this is a
# per-book step, not a per-chapter one -- see COMMON_IMAGE above). The
# pristine _quarto.yml is mounted alongside the site read-only, purely for
# its babelquarto metadata (language list + display labels); it is never
# written to.
#
# --no-inject skips it, and a caller that splits languages across machines
# MUST use it. inject_language_links.R is NOT idempotent: add_dropdown_links()
# REUSES an existing <ul id="languages-links"> rather than rebuilding it, so
# injecting per-language and then again over the assembled site APPENDS a
# second set of links to every translated page instead of replacing the first.
# Inject exactly once, over the complete tree.
if [ "$DO_INJECT" -eq 1 ]; then
  if ! docker run --rm \
      -v "$OUTPUT_DIR:/site" \
      -v "$HANDBOOK_DIR/_quarto.yml:/quarto/_quarto.yml:ro" \
      -w /site "$COMMON_IMAGE" \
      inject_language_links.sh /site /quarto/_quarto.yml; then
    fail "inject_language_links.sh failed over the assembled site at $OUTPUT_DIR"
  fi
else
  echo "build_all_chapters.sh: --no-inject -- skipping the language-switcher pass; the caller must run it once over the assembled site"
fi

echo "build_all_chapters.sh: done -- $OUTPUT_DIR is ready to publish"
