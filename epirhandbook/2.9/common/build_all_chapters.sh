#!/bin/bash
# build_all_chapters.sh -- render every chapter, in every language, and
# assemble one output tree.
#
# THIS RUNS ON THE CI RUNNER, NOT INSIDE A CONTAINER. It starts one
# container per chapter render (docker run ... build_one_chapter.sh ...),
# so running it inside a container itself would need docker-in-docker. It
# is nonetheless STORED in epirhandbook-common:2.9 (this file lives at
# common/build_all_chapters.sh and is COPYed onto PATH by common/Dockerfile,
# exactly like build_one_chapter.sh), so there is a single source of truth
# for it. The CI runner extracts it before running it:
#   docker run --rm <common-image> cat /usr/local/bin/build_all_chapters.sh > build_all.sh
#
# THE LAYOUT THIS BUILDS. Every handbook language is its own Quarto book
# project, at content/<lang>/ in the handbook checkout. Chapter S of
# language L is the source file content/L/S.qmd, index included, with no
# special case. Each project's own content/L/_quarto.yaml declares that
# language, its title and its chapter list, and renders into
# content/L/html_outputs/. Nothing here rewrites a config, and nothing
# renames a source file per language.
#
# WHY ONE .qmd AT A TIME: the whole book used to be rendered by one call.
# This script renders one .qmd at a time instead, each in its own pinned
# image. A chapter can therefore be pinned back to an older image (a
# previous epirhandbook-basics tag, say) independently of the rest of the
# book.
#
# INPUTS, all in the handbook checkout given as <handbook_dir>:
#   languages.yml              the one language list: `main`, `languages[].code`
#   docker-images.yml          the chapter -> image manifest
#   content/<lang>/            one Quarto book project per declared language
#   content/<lang>/_quarto.yaml  that project's own config
#   images/                    the shared image assets the pages link to
# Plus <registry_prefix>, which every image is pulled from.
#
# WHY NOT A LANGUAGE LIST ARGUMENT: languages.yml is the single source of
# truth for which languages ship. This script reads it, inject_language_links.R
# reads it, and the handbook's own workflow reads it. Accepting a language
# list here too would be a second, driftable source of the same fact.
#
# THE MANIFEST (docker-images.yml, at the HANDBOOK repo's root -- not this
# repo): one row per chapter, covering every language of that chapter.
#   registry: ghcr.io/appliedepi/aedockerpublic
#   chapters:
#     - stem: time_series
#       image: epirhandbook-analysis:2.9
#     - stem: basics
#       image: epirhandbook-basics:2.9-old   # deliberately pinned back (illustrative tag)
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
#      "${RENDER_LANGS[@]}"` loop below, which deliberately does NOT do so.
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
  echo "                      languages.yml. Its site lands at the ROOT of <output_dir>, with no" >&2
  echo "                      <lang>/ nesting. Use one leg per language in a CI matrix." >&2
  echo "                      REQUIRES --no-inject." >&2
  echo "  --no-inject         skip the language-switcher pass. REQUIRED when languages are split" >&2
  echo "                      across legs: the injector is not idempotent, so it must run exactly" >&2
  echo "                      once, over the fully assembled site." >&2
  echo "  <handbook_dir>      checkout of the handbook repo (has languages.yml + docker-images.yml)" >&2
  echo "  <registry_prefix>   e.g. ghcr.io/appliedepi/aedockerpublic -- images are '<registry_prefix>/<image>'" >&2
  echo "  <output_dir>        where the assembled site is written (default: ./html_outputs)" >&2
}

# --- book-level tooling always runs against THIS common image. It never
# --- runs against the (possibly pinned-back) image a chapter renders in.
# --- The language-link injection is a per-BOOK step, not a per-chapter
# --- one. Whether the image a chapter renders in also carries
# --- inject_language_links.R is irrelevant. This script itself lives in
# --- epirhandbook/2.9, so "2.9" is the correct common tag for it to use.
COMMON_TAG="2.9"

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

# --only-lang without --no-inject is refused HERE, in argument parsing,
# before any directory is read and before any container starts. The
# switcher is defined over the ASSEMBLED site: a link from one language's
# page to another's needs both pages in one tree. A leg holding one language
# has no other language to link to, so injecting there writes a switcher
# with nothing in it. The injector is not idempotent, so the assembled
# site's own injection pass then appends a SECOND set of links.
if [ -n "$ONLY_LANG" ] && [ "$DO_INJECT" -eq 1 ]; then
  echo "build_all_chapters.sh: --only-lang needs --no-inject." >&2
  echo "  Inject once, over the assembled site, after every leg has landed." >&2
  usage
  exit 2
fi

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  usage
  exit 2
fi
HANDBOOK_DIR_ARG="$1"
REGISTRY_PREFIX="$2"
OUTPUT_DIR="${3:-$PWD/html_outputs}"

[ -d "$HANDBOOK_DIR_ARG" ] || fail "no such directory: $HANDBOOK_DIR_ARG"
HANDBOOK_DIR="$(cd "$HANDBOOK_DIR_ARG" && pwd)"
[ -f "$HANDBOOK_DIR/languages.yml" ] || fail "no languages.yml in $HANDBOOK_DIR"
[ -f "$HANDBOOK_DIR/docker-images.yml" ] || fail "no docker-images.yml in $HANDBOOK_DIR"
[ -d "$HANDBOOK_DIR/content" ] || fail "no content/ directory in $HANDBOOK_DIR"
[ -d "$HANDBOOK_DIR/images" ] || fail "no images/ directory in $HANDBOOK_DIR -- the assembled site links to it"
[ -n "$REGISTRY_PREFIX" ] || fail "registry prefix (arg 2) must not be empty"

COMMON_IMAGE="$REGISTRY_PREFIX/epirhandbook-common:$COMMON_TAG"

# --- read the language list from languages.yml (the single source of truth) --
# Uses real PyYAML, matching this repo's own established rule for reading
# YAML (see .github/scripts/requirements.txt's header): no hand-rolled
# parser, ever, for the same reasons that file documents at length.
# `main` MUST be one of the declared codes. It names the language the root
# redirect stub points at. A `main` outside the list would publish a
# redirect to a directory this build never writes.
read_languages() {
  python3 - "$HANDBOOK_DIR/languages.yml" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as fh:
    cfg = yaml.safe_load(fh) or {}
main = cfg.get("main")
entries = cfg.get("languages") or []
codes = []
for entry in entries:
    if not isinstance(entry, dict) or not entry.get("code"):
        sys.exit("::error::build_all_chapters.sh: every languages[] entry needs a 'code': " + repr(entry))
    codes.append(entry["code"])
if not main:
    sys.exit("::error::build_all_chapters.sh: 'main' missing from " + sys.argv[1])
if not codes:
    sys.exit("::error::build_all_chapters.sh: 'languages' missing or empty in " + sys.argv[1])
if main not in codes:
    sys.exit(
        "::error::build_all_chapters.sh: main language '%s' is not one of the declared codes %s in %s"
        % (main, codes, sys.argv[1])
    )
print(main)
print(" ".join(codes))
PY
}

lang_info_file="$(mktemp)"
if ! read_languages > "$lang_info_file"; then
  cat "$lang_info_file" >&2
  rm -f "$lang_info_file"
  fail "could not read the language list from $HANDBOOK_DIR/languages.yml"
fi
MAIN="$(sed -n '1p' "$lang_info_file")"
read -r -a DECLARED_LANGS <<< "$(sed -n '2p' "$lang_info_file")"
rm -f "$lang_info_file"

# DECLARED_LANGS is every language the handbook ships. RENDER_LANGS is what
# THIS run renders, which --only-lang narrows to one. The manifest check
# below stays on DECLARED_LANGS. A matrix leg then still catches a chapter
# list that has drifted in a language it does not itself render.
RENDER_LANGS=("${DECLARED_LANGS[@]}")

# --only-lang narrows the run to ONE of the declared languages. It never
# invents one: the code must already be in that list. This cannot render
# something the book does not ship.
#
# LAYOUT NOTE, load-bearing for the caller: under --only-lang the OUTPUT_DIR
# holds that language's site AT ITS ROOT, with no <lang>/ nesting -- there is
# nothing to nest it under, because no other language was rendered. A CI leg
# uploads that directory as-is; whoever assembles the legs decides where each
# one lands, and writes the images/ copy and the root redirect stub that a
# full run writes here.
if [ -n "$ONLY_LANG" ]; then
  found=0
  for l in "${DECLARED_LANGS[@]}"; do
    if [ "$l" = "$ONLY_LANG" ]; then found=1; fi
  done
  [ "$found" -eq 1 ] || fail "--only-lang '$ONLY_LANG' is not one of languages.yml's declared codes (${DECLARED_LANGS[*]})"
  RENDER_LANGS=("$ONLY_LANG")
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

# --- one language's declared chapter stems, in book order -------------------
# The book is what a language's own _quarto.yaml DECLARES, not what happens
# to be on disk beside it. content/<lang>/ also holds obsolete drafts, and
# any chapter deliberately commented out. Globbing the directory instead of
# reading the config demands a manifest row for every one of those. It
# fails the build outright, which is exactly what it did.
book_stems() {
  python3 - "$1" <<'PY'
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
for path in paths:
    print(path[: -len(".qmd")])
PY
}

# --- do not silently skip a chapter with no manifest entry ------------------
# Every chapter the book declares must have a manifest row. A chapter the
# manifest never mentions is a MISSING ENTRY, not a chapter to quietly
# skip: someone added a chapter and forgot the manifest.
#
# Checked in BOTH directions, because each catches a different mistake. A
# declared chapter with no row means someone added a chapter and forgot the
# manifest. A row for an undeclared chapter means one of two things. The
# manifest would render an orphan page that is in no book, or it names an
# image that need not exist.
#
# Then checked across languages. Every declared language is the SAME book,
# so every content/<lang>/_quarto.yaml must flatten to the same stem list in
# the same order. A translation that has quietly lost a chapter, or ordered
# its sidebar differently, is a defect in the book and not something to
# render around. The reference is the main language's project file, which is
# content/en/_quarto.yaml today.
check_manifest_covers_book() {
  local ref declared missing extra lang other stem
  ref="$HANDBOOK_DIR/content/$MAIN/_quarto.yaml"
  [ -f "$ref" ] || fail "no '$ref' -- the main language has no Quarto project file"
  declared="$(book_stems "$ref")" || fail "could not read book.chapters from $ref"
  [ -n "$declared" ] || fail "$ref declares no .qmd chapter at all"

  missing=""
  while IFS= read -r stem; do
    [ -n "$stem" ] || continue
    grep -q -P "^${stem}\t" "$MANIFEST_FILE" || missing="$missing $stem"
  done <<< "$declared"
  [ -z "$missing" ] || fail "chapter(s) declared in $ref with no docker-images.yml entry:$missing -- add a manifest row for each"

  extra=""
  while IFS=$'\t' read -r stem _; do
    grep -q -x -F "$stem" <<< "$declared" || extra="$extra $stem"
  done < "$MANIFEST_FILE"
  [ -z "$extra" ] || fail "docker-images.yml has row(s) for chapter(s) that $ref does not declare:$extra -- remove them, or add the chapter to book.chapters"

  for lang in "${DECLARED_LANGS[@]}"; do
    [ -f "$HANDBOOK_DIR/content/$lang/_quarto.yaml" ] \
      || fail "no '$HANDBOOK_DIR/content/$lang/_quarto.yaml' -- languages.yml declares '$lang', so that project must exist"
    other="$(book_stems "$HANDBOOK_DIR/content/$lang/_quarto.yaml")" \
      || fail "could not read book.chapters from $HANDBOOK_DIR/content/$lang/_quarto.yaml"
    [ "$other" = "$declared" ] || fail "content/$lang/_quarto.yaml declares a different chapter list from content/$MAIN/_quarto.yaml -- '$lang' has [$(echo "$other" | tr '\n' ' ')], '$MAIN' has [$(echo "$declared" | tr '\n' ' ')]. Same set, same order, or the two are not the same book."
  done
}
check_manifest_covers_book

WORK_ROOT="$(mktemp -d)"
echo "build_all_chapters.sh: workspace root: $WORK_ROOT (not auto-cleaned -- inspect on failure)"

# --- one fresh workspace per language, ALWAYS from the pristine checkout ----
# Each language renders into its own copy, so one language's `.quarto/` state
# can never reach another's render.
#
# The excludes are load-bearing. A developer's local checkout can already
# hold content/<lang>/html_outputs from a previous run. validate_language()
# below proves this build's own output by looking for exactly those files.
# A stale tree copied in would satisfy it with no render at all. The
# same goes for content/<lang>/.quarto (the xref and search state pass 1
# exists to build) and content/<lang>/<stem>_files (a page's figures). .git
# is excluded because it is large and no render reads it.
prepare_workspace() {
  local lang="$1" ws="$WORK_ROOT/$lang"
  rm -rf "$ws"
  mkdir -p "$ws"
  if ! rsync -a \
      --exclude 'content/*/html_outputs' \
      --exclude 'content/*/.quarto' \
      --exclude 'content/*/*_files' \
      --exclude '.git' \
      "$HANDBOOK_DIR"/ "$ws"/; then
    fail "lang=$lang: could not copy $HANDBOOK_DIR into the workspace $ws"
  fi
  [ ! -e "$ws/content/$lang/html_outputs" ] \
    || fail "lang=$lang: '$ws/content/$lang/html_outputs' survived the workspace copy -- the exclude list is not doing its job"
}

# --- render every manifest chapter once, for one language ONE pass ---------
# SEQUENTIAL BY CONSTRUCTION: this is a plain bash `while read` loop with no
# backgrounding (`&`), so chapter N+1 never starts before chapter N's
# `docker run` has exited. That is what honours finding 3 (search.json
# would race under parallel renders within a language).
#
# The container's working directory is the language's own project,
# /book/content/<lang>, and the argument is the bare <stem>.qmd inside it.
# build_one_chapter.sh's header says why that matters: a render started
# anywhere else is not a project render, and it exits 0 anyway.
render_pass() {
  local lang="$1" ws="$2" pass="$3"
  local stem image qmd image_ref
  while IFS=$'\t' read -r stem image; do
    qmd="$ws/content/$lang/$stem.qmd"
    if [ ! -f "$qmd" ]; then
      fail "lang=$lang pass=$pass: expected source '$qmd' for chapter '$stem' does not exist"
    fi
    image_ref="$REGISTRY_PREFIX/$image"
    echo "build_all_chapters.sh: lang=$lang pass=$pass: rendering $stem.qmd with $image_ref"
    if ! docker run --rm -v "$ws:/book" -w "/book/content/$lang" "$image_ref" build_one_chapter.sh "$stem.qmd"; then
      fail "lang=$lang pass=$pass: chapter '$stem' failed to render 'content/$lang/$stem.qmd' using '$image_ref'"
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
  local outdir="$ws/content/$lang/html_outputs"
  local search="$outdir/search.json"
  local stem image html

  [ -d "$outdir" ] || fail "lang=$lang: no '$outdir' -- nothing was rendered"
  [ -f "$search" ] || fail "lang=$lang: '$search' is missing -- no search index was produced"

  # Every chapter of a language sits directly in that language's project, so
  # <stem>.qmd renders to html_outputs/<stem>.html and search.json's href is
  # that same "<stem>.html". The href is compared verbatim, quotes included,
  # so "basics.html" cannot be satisfied by "new_pages/basics.html".
  while IFS=$'\t' read -r stem image; do
    html="$outdir/$stem.html"
    [ -f "$html" ] || fail "lang=$lang: expected output '$html' (chapter '$stem', via '$image') was never produced"
    grep -F -q "\"$stem.html\"" "$search" \
      || fail "lang=$lang: '$search' does not reference '$stem.html' (chapter '$stem')"
  done < "$MANIFEST_FILE"

  # Dead-same-page-link check: every href="#frag" must have a matching
  # id="frag" IN THE SAME FILE. href="#" (an empty fragment) is excluded
  # deliberately -- it is a JS-hook placeholder used by dropdown/toggle
  # controls in the page template, never a same-page anchor, and same-page
  # anchors are never empty strings.
  # Dead same-page fragments are REPORTED, never fatal. It is tempting to fail
  # the build on them -- that is the exact symptom of the cross-reference bug
  # the second render pass exists to fix. It does not work as a gate, and this
  # was measured, not assumed. The measurement is the whole-book reference
  # render of the real 49-chapter book, which is the 2.7 book. It was the live
  # site at the time. That render contains 106 dead fragments of its own after
  # percent-decoding, and 4552 before it. They are pre-existing content bugs
  # -- `#gis` 15 times, `#contact_us` 7 -- not render faults. A gate here would
  # fail every build forever, and a numeric threshold would be arbitrary.
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
for lang in "${RENDER_LANGS[@]}"; do
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
# EVERY language lands under its own directory, the main language included:
# the site is $OUTPUT_DIR/<lang>/..., and $OUTPUT_DIR/index.html is a
# redirect stub to the main language. No language sits at the root. The
# root is therefore not one language's site with the others bolted on, and
# the switcher's hrefs are the same shape on every page.
rm -rf "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"
if [ -n "$ONLY_LANG" ]; then
  cp -a "$WORK_ROOT/$ONLY_LANG/content/$ONLY_LANG/html_outputs"/. "$OUTPUT_DIR"/
  echo "build_all_chapters.sh: assembled $OUTPUT_DIR (only lang=$ONLY_LANG, at the root; no images/ copy and no redirect stub -- whoever joins the legs writes those)"
else
  for lang in "${RENDER_LANGS[@]}"; do
    mkdir -p "$OUTPUT_DIR/$lang"
    cp -a "$WORK_ROOT/$lang/content/$lang/html_outputs"/. "$OUTPUT_DIR/$lang"/
  done
  # The pages reference images/ from the site root, and no language's render
  # copies it, so it is copied once here.
  mkdir -p "$OUTPUT_DIR/images"
  cp -a "$HANDBOOK_DIR/images"/. "$OUTPUT_DIR/images"/
  # The root redirect stub. Four lines, and the only page at the site root.
  printf '%s\n' \
    '<!DOCTYPE html>' \
    "<html lang=\"$MAIN\"><head><meta charset=\"utf-8\"><title>Redirect to $MAIN/</title>" \
    "<meta http-equiv=\"refresh\" content=\"0;URL='$MAIN/'\"><link rel=\"canonical\" href=\"$MAIN/\"></head>" \
    '<body></body></html>' \
    > "$OUTPUT_DIR/index.html"
  echo "build_all_chapters.sh: assembled $OUTPUT_DIR (languages=${RENDER_LANGS[*]}, images/ copied, root redirects to $MAIN/)"
fi

# --- the language-switcher post-pass ----------------------------------------
# Runs once, over the FULLY ASSEMBLED tree, in the common image (this is a
# per-book step, not a per-chapter one -- see COMMON_IMAGE above).
# languages.yml is mounted alongside the site read-only, for the language
# list and the dropdown's display labels; it is never written to.
#
# --no-inject skips it, and a caller that splits languages across machines
# MUST use it. inject_language_links.R is NOT idempotent: add_dropdown_links()
# REUSES an existing <ul id="languages-links"> rather than rebuilding it, so
# injecting per-language and then again over the assembled site APPENDS a
# second set of links to every page instead of replacing the first.
# Inject exactly once, over the complete tree.
if [ "$DO_INJECT" -eq 1 ]; then
  if ! docker run --rm \
      -v "$OUTPUT_DIR:/site" \
      -v "$HANDBOOK_DIR/languages.yml:/quarto/languages.yml:ro" \
      -w /site "$COMMON_IMAGE" \
      inject_language_links.sh /site /quarto/languages.yml; then
    fail "inject_language_links.sh failed over the assembled site at $OUTPUT_DIR"
  fi
else
  echo "build_all_chapters.sh: --no-inject -- skipping the language-switcher pass; the caller must run it once over the assembled site"
fi

echo "build_all_chapters.sh: done -- $OUTPUT_DIR is ready to publish"
