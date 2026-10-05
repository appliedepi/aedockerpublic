#!/bin/bash
# build_all_chapters.sh: render every chapter in every language, and
# assemble one output tree.
#
# THIS SCRIPT RUNS ON THE CI RUNNER, NOT IN A CONTAINER. It starts one
# container for each chapter render (docker run ... build_one_chapter.sh
# ...). To run it in a container would need docker-in-docker. But it is
# STORED in epirhandbook-common:2.9, so there is one copy of it. The file is
# common/build_all_chapters.sh, and common/Dockerfile COPYs it onto PATH, as
# it does build_one_chapter.sh. The CI runner extracts it before it runs it:
#   docker run --rm <common-image> cat /usr/local/bin/build_all_chapters.sh > build_all.sh
#
# THE LAYOUT THAT THIS SCRIPT BUILDS. Each handbook language is its own
# Quarto book project, at content/<lang>/ in the handbook checkout. Chapter S
# of language L is the source file content/L/S.qmd. This includes index, with
# no special case. The content/L/_quarto.yaml of each project declares the
# language, its title and its chapter list, and renders into
# content/L/html_outputs/. This script does not rewrite a config, and it
# does not rename a source file for each language.
#
# WHY ONE .qmd AT A TIME: before, one call rendered the whole book. This
# script renders one .qmd at a time, each in its own pinned image. Thus you
# can pin one chapter back to an older image, such as an earlier
# epirhandbook-basics tag. The rest of the book does not change.
#
# INPUTS, all in the handbook checkout given as <handbook_dir>:
#   languages.yml              the one language list: `main`, `languages[].code`
#   docker-images.yml          the chapter -> image manifest
#   content/<lang>/            one Quarto book project per declared language
#   content/<lang>/_quarto.yaml  that project's own config
#   images/                    the shared image assets the pages link to
# Plus <registry_prefix>, which every image is pulled from.
#
# WHY THERE IS NO ARGUMENT FOR THE LANGUAGE LIST: languages.yml is the one
# source for the languages that ship. This script, inject_language_links.R
# and the workflow of the handbook all read it. A language list argument
# would be a second source of the same fact, and the two could disagree.
#
# THE MANIFEST is docker-images.yml, at the root of the HANDBOOK repo, not
# this repo. It has one row for each chapter, for all languages of that
# chapter.
#   registry: ghcr.io/appliedepi/aedockerpublic
#   chapters:
#     - stem: time_series
#       image: epirhandbook-analysis:2.9
#     - stem: basics
#       image: epirhandbook-basics:2.9-old   # pinned back (example tag)
# A book chapter with no manifest row is a MISSING ENTRY. The script does not
# render it with a guessed default. See check_manifest_covers_book() below.
#
# TWO HARD CONSTRAINTS. Both were measured.
#   1. All renders of one language MUST share one persistent workspace and
#      run ONE AFTER ANOTHER. Quarto adds each separate render to the
#      project search index (search.json), through the `.quarto/` state
#      directory on the shared mount. Parallel renders in one language would
#      race on it. Different LANGUAGES use separate workspaces, so they
#      cannot race, and they MAY run in parallel. The `for lang in
#      "${RENDER_LANGS[@]}"` loop below does NOT run them in parallel.
#   2. EVERY CHAPTER MUST BE RENDERED TWICE, in the same workspace. Suppose
#      a chapter renders before its cross-reference target is in
#      `.quarto/xref`. The link then becomes a same-page anchor that does not
#      exist on that page: a dead link. One small spike measured 3 of them.
#      A second full pass, after every chapter is registered once, resolves
#      them. In that spike, the second pass took the dead-link count from 3
#      to 0, and the output was byte-identical to the whole-book reference.
#      Do not remove pass 2. Without it, the dead-fragment check in
#      validate_language() fails the build.
#
# FAIL LOUDLY: if a chapter does not render, this build fails at once. The
# message names the chapter, the language and the pass. An exit status of 0
# from a render is not sufficient. An earlier version of this build
# measured 24 renders that exited 0 and gave unusable output. The checks in
# validate_language() below find that.
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

# --- Tools for the whole book always run against THIS common image, never
# --- against the image that a chapter renders in, which can be pinned back.
# --- The language-link pass is a step for the whole BOOK, not for one
# --- chapter. It does not matter whether a chapter image also holds
# --- inject_language_links.R. This script is in epirhandbook/2.9, so "2.9"
# --- is the correct common tag for it.
COMMON_TAG="2.9"

# --- The R profile of every chapter render. common/Dockerfile COPYs
# --- common/warnings_to_log.R to this path. build_one_chapter.sh fails when
# --- R_PROFILE_USER names a file that the image does not hold, because R
# --- ignores a missing profile and gives no message.
R_PROFILE_IN_IMAGE="/usr/local/lib/ehb/warnings_to_log.R"

# --- arg parsing -------------------------------------------------------------
# Two optional flags let a CI matrix put ONE language in each leg. Without
# them, a caller must render every language in every leg and discard most of
# the output. The caller must also remove the switcher markup of this script
# from the HTML afterwards. The first version of the handbook workflow did
# both of these things.
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

# The script refuses --only-lang without --no-inject HERE, in argument
# parsing. No directory is read and no container starts before this check.
# The switcher works on the ASSEMBLED site. A link from a page in one
# language to a page in another needs both pages in one tree. A leg with one
# language has no other language to link to, so the pass there writes an
# empty switcher. The injector is not idempotent, so the later pass over the
# assembled site then adds a SECOND set of links.
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
# The script uses rsync to copy the handbook into each language workspace.
# ubuntu-latest has it. Check here, so a different runner fails with a clear
# message before any work starts.
command -v rsync >/dev/null 2>&1 || fail "rsync is not on PATH. This script needs it to copy the handbook into each workspace"
[ -n "$REGISTRY_PREFIX" ] || fail "registry prefix (arg 2) must not be empty"

COMMON_IMAGE="$REGISTRY_PREFIX/epirhandbook-common:$COMMON_TAG"

# --- Read the language list from languages.yml, the one source of it ------
# This uses PyYAML. The header of .github/scripts/requirements.txt gives the
# rule of this repo for YAML: use a real parser, not a hand-written one.
# `main` MUST be one of the declared codes. It names the language that the
# root redirect stub points at. A `main` outside the list would publish a
# redirect to a directory that this build does not write.
read_languages() {
  python3 - "$HANDBOOK_DIR/languages.yml" <<'PY'
import sys
import yaml

# BaseLoader keeps every scalar a string. yaml.safe_load reads an unquoted
# `no` as False, so the Norwegian code `no` would fail the 'code' check below.
with open(sys.argv[1]) as fh:
    cfg = yaml.load(fh, Loader=yaml.BaseLoader) or {}
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

# DECLARED_LANGS is every language that the handbook ships. RENDER_LANGS is
# the languages that THIS run renders, and --only-lang makes it one. The
# manifest check below uses DECLARED_LANGS. Thus a matrix leg also finds a
# chapter list that differs in a language that the leg does not render.
RENDER_LANGS=("${DECLARED_LANGS[@]}")

# --only-lang limits the run to ONE of the declared languages. The code MUST
# already be in that list, so the run cannot render a language that the book
# does not ship.
#
# LAYOUT NOTE FOR THE CALLER: with --only-lang, OUTPUT_DIR holds the site of
# that language AT ITS ROOT, with no <lang>/ directory. No other language was
# rendered, so there is no reason for one. A CI leg uploads that directory
# as it is. The step that joins the legs decides where each one goes. That
# step also writes the images/ copy and the root redirect stub, which a full
# run writes here.
if [ -n "$ONLY_LANG" ]; then
  found=0
  for l in "${DECLARED_LANGS[@]}"; do
    if [ "$l" = "$ONLY_LANG" ]; then found=1; fi
  done
  [ "$found" -eq 1 ] || fail "--only-lang '$ONLY_LANG' is not one of languages.yml's declared codes (${DECLARED_LANGS[*]})"
  RENDER_LANGS=("$ONLY_LANG")
  echo "build_all_chapters.sh: --only-lang $ONLY_LANG -- rendering that language alone, output at the root of $OUTPUT_DIR"
fi

# --- Read the chapter->image manifest ---------------------------------------
# docker-images.yml is at the root of the HANDBOOK repo, which is a separate
# repo. The script reads it from the checkout given as $HANDBOOK_DIR.
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

# --- The declared chapter stems of one language, in book order -------------
# The book is what the _quarto.yaml of a language DECLARES, not the files
# next to it. content/<lang>/ also holds old drafts and chapters that are
# commented out. A glob of the directory, in place of a read of the config,
# needs a manifest row for each of those files. It then fails the build. An
# earlier version used a glob, and the build failed.
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

# --- Do not skip a chapter that has no manifest row ------------------------
# Every chapter that the book declares MUST have a manifest row. A chapter
# with no row is a MISSING ENTRY, and the build fails.
#
# The check works in BOTH directions, because each direction finds a
# different mistake. A declared chapter with no row means that someone added
# a chapter and did not add it to the manifest. A row for an undeclared
# chapter has one of two causes:
#   - the manifest would render an orphan page that is in no book.
#   - the row names an image that does not need to exist.
#
# Then the check compares the languages. Every declared language is the SAME
# book, so every content/<lang>/_quarto.yaml MUST give the same stem list in
# the same order. A translation that lost a chapter, or that has a different
# sidebar order, is a defect in the book. The build fails on it. The
# reference is the project file of the main language, which today is
# content/en/_quarto.yaml.
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
echo "build_all_chapters.sh: workspace root: $WORK_ROOT (removed after a successful build, kept after a failure)"

# --- One new workspace for each language, ALWAYS from the clean checkout ---
# Each language renders into its own copy, so the `.quarto/` state of one
# language cannot reach the render of another.
#
# The excludes are necessary. A local checkout of a developer can already
# hold content/<lang>/html_outputs from an earlier run. validate_language()
# below checks the output of this build by looking for those files. A stale
# tree copied in would pass that check with no render. The same is true for
# content/<lang>/.quarto, the xref and search state that pass 1 builds, and
# for content/<lang>/<stem>_files, the figures of a page. .git is excluded
# because it is large and no render reads it.
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

# --- Render every manifest chapter once, for one language: ONE pass -------
# The renders run ONE AFTER ANOTHER. This is a plain bash `while read` loop
# with no background jobs (`&`). Thus chapter N+1 starts only after the
# `docker run` of chapter N exits. Parallel renders in one language would
# race on search.json.
#
# The working directory of the container is the project of the language,
# /book/content/<lang>. The argument is the bare <stem>.qmd in it. The
# header of build_one_chapter.sh says why: a render started in any other
# directory is not a project render, and it exits 0 all the same.
#
# The container has NO NETWORK (--network none). A chapter that installs a
# missing package during the render, or downloads data, fails here. With a
# network, the render installs the package and exits 0, and nothing shows
# the defect in the image. The image holds every package, and the checkout
# holds the data, so a correct chapter needs no network.
#
# R_PROFILE_USER points R at warnings_to_log.R, which common/Dockerfile
# installs at $R_PROFILE_IN_IMAGE. The profile writes one EHB-WARNING line to
# the log for each R warning that a chunk raises. This is true for any value
# of the `warning` option of the chunk. It writes one EHB-ERROR line for each error
# that an `error: true` chunk captures. The page does not change. The header
# of warnings_to_log.R says how.
#
# An image built before warnings_to_log.R existed does not hold the profile,
# and its build_one_chapter.sh does not check for it. R then ignores
# R_PROFILE_USER, and the chapter logs no warnings. Thus
# check_image_has_profile() checks each image for the profile once, before
# the first render in that image.
declare -A IMAGE_HAS_PROFILE=()
check_image_has_profile() {
  local image_ref="$1" stem="$2"
  [ -z "${IMAGE_HAS_PROFILE[$image_ref]:-}" ] || return 0
  # `test -r` exits 1 when the file is missing. Any other non-zero exit is
  # a docker failure (125 to 127), such as an image that cannot be pulled,
  # or a failure of the image's entrypoint.
  local rc=0
  docker run --rm --network none "$image_ref" test -r "$R_PROFILE_IN_IMAGE" || rc=$?
  if [ "$rc" -eq 1 ]; then
    fail "chapter '$stem' renders in '$image_ref', which holds no readable '$R_PROFILE_IN_IMAGE'. The image is probably older than warnings_to_log.R, so the render would log no warnings. Move the chapter to a newer image in docker-images.yml."
  elif [ "$rc" -ne 0 ]; then
    fail "chapter '$stem': could not run '$image_ref' to check for '$R_PROFILE_IN_IMAGE' (exit $rc)"
  fi
  IMAGE_HAS_PROFILE[$image_ref]=1
}

render_pass() {
  local lang="$1" ws="$2" pass="$3"
  local stem image qmd image_ref
  while IFS=$'\t' read -r stem image; do
    qmd="$ws/content/$lang/$stem.qmd"
    if [ ! -f "$qmd" ]; then
      fail "lang=$lang pass=$pass: expected source '$qmd' for chapter '$stem' does not exist"
    fi
    image_ref="$REGISTRY_PREFIX/$image"
    check_image_has_profile "$image_ref" "$stem"
    echo "build_all_chapters.sh: lang=$lang pass=$pass: rendering $stem.qmd with $image_ref"
    if ! docker run --rm --network none -e "R_PROFILE_USER=$R_PROFILE_IN_IMAGE" \
        -v "$ws:/book" -w "/book/content/$lang" "$image_ref" build_one_chapter.sh "$stem.qmd"; then
      fail "lang=$lang pass=$pass: chapter '$stem' failed to render 'content/$lang/$stem.qmd' using '$image_ref'"
    fi
  done < "$MANIFEST_FILE"
}

# --- Validate before the assembly. Exit status 0 is not sufficient --------
# An earlier version measured 24 renders that exited 0 and gave unusable output. A
# check of exit status alone misses each of these three cases. They are in
# order of how much each would have found:
#   (a) the render did not make the file.
#   (b) the render made the file, but did not add it to the search index.
#   (c) the file exists and is in the index, but it has a dead same-page
#       link. This check would have found the dead-link regression of
#       that version, so it is the most important.
validate_language() {
  local lang="$1" ws="$2"
  local outdir="$ws/content/$lang/html_outputs"
  local search="$outdir/search.json"
  local stem image html

  [ -d "$outdir" ] || fail "lang=$lang: no '$outdir' -- nothing was rendered"
  [ -f "$search" ] || fail "lang=$lang: '$search' is missing -- no search index was produced"

  # Every chapter of a language is directly in the project of that language.
  # Thus <stem>.qmd renders to html_outputs/<stem>.html, and the href in
  # search.json is the same "<stem>.html". The check compares the href with
  # its quotes, so "new_pages/basics.html" does not match "basics.html".
  while IFS=$'\t' read -r stem image; do
    html="$outdir/$stem.html"
    [ -f "$html" ] || fail "lang=$lang: expected output '$html' (chapter '$stem', via '$image') was never produced"
    grep -F -q "\"$stem.html\"" "$search" \
      || fail "lang=$lang: '$search' does not reference '$stem.html' (chapter '$stem')"
  done < "$MANIFEST_FILE"

  # Dead same-page link check: every href="#frag" MUST have a matching
  # id="frag" IN THE SAME FILE. The check skips href="#", an empty fragment.
  # The dropdown and toggle controls of the page template use it as a
  # placeholder for JS. It is not a same-page anchor, and a same-page anchor
  # is never an empty string.
  # A dead same-page fragment FAILS the build. So does a failed count: the
  # python step fails, or prints something that is not a count. The failure
  # message names every dead fragment as <page>#<fragment>.
  #
  # Before 2026-10-01, the script only printed the count, and a failed count
  # printed "?". The reason was the 2.7 whole-book render of 49 chapters. It
  # held 106 dead fragments, all content bugs (`#gis` 15 times, `#contact_us`
  # 7 times). A printed count that nobody reads protects nothing. Thus the
  # handbook MUST fix those content bugs before its build can pass.
  #
  # The check decodes percent-encoding. An href fragment is URL-encoded
  # (`#r%C3%A9visions-majeures`), and the matching `id=` is not. A literal
  # comparison reports about 40 times more "dead" links than there are.
  local dead n
  if ! dead="$(python3 - "$outdir" <<'PY'
import re, glob, os, sys, urllib.parse
root = sys.argv[1]
files = sorted(f for f in glob.glob(root + "/**/*.html", recursive=True) if "/site_libs/" not in f)
found = []
for path in files:
    text = open(path, encoding="utf-8", errors="replace").read()
    ids = set(re.findall(r'id="([^"]*)"', text))
    for frag in sorted(set(re.findall(r'href="#([^"]*)"', text))):
        if frag and frag not in ids and urllib.parse.unquote(frag) not in ids:
            found.append(os.path.relpath(path, root) + "#" + urllib.parse.unquote(frag))
print(len(found), " ".join(found))
PY
)"; then
    fail "lang=$lang: could not count the dead same-page fragments in '$outdir'"
  fi
  n="${dead%% *}"
  [[ "$n" =~ ^[0-9]+$ ]] || fail "lang=$lang: the dead same-page fragment count is not a number: '$dead'"
  [ "$n" -eq 0 ] || fail "lang=$lang: $n dead same-page fragment(s): ${dead#* }"
  echo "build_all_chapters.sh: lang=$lang: dead same-page fragments: 0"
}

# This loop is a plain `for`, one language after another. The languages use
# separate workspaces and COULD run in parallel (see constraint 1 above). To
# run them as background jobs, the script would have to keep the exit status
# of each subshell. A lost background failure breaks the "fail loudly" rule
# above. That extra code is not tested and not needed now. A later version
# MAY run the languages in parallel.
for lang in "${RENDER_LANGS[@]}"; do
  ws="$WORK_ROOT/$lang"
  prepare_workspace "$lang"
  # Pass 1 adds the targets of every chapter to .quarto/xref.
  render_pass "$lang" "$ws" 1
  # Pass 2 is necessary (constraint 2 in the header). It
  # renders every chapter again, now that the cross-reference targets of
  # every OTHER chapter are known. The links then resolve, and do not become
  # same-page fragments.
  render_pass "$lang" "$ws" 2
  validate_language "$lang" "$ws"
done

# --- Assemble one output tree -----------------------------------------------
# EVERY language, the main language included, goes in its own directory. The
# site is $OUTPUT_DIR/<lang>/..., and $OUTPUT_DIR/index.html is a redirect
# stub to the main language. No language is at the root. Thus the root is not
# the site of one language with the other languages added to it. Also, the
# switcher hrefs have the same form on every page.
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
  # The pages refer to images/ at the site root. No language render copies
  # it, so the script copies it once here.
  mkdir -p "$OUTPUT_DIR/images"
  cp -a "$HANDBOOK_DIR/images"/. "$OUTPUT_DIR/images"/
  # The root redirect stub: four lines, and the only page at the site root.
  printf '%s\n' \
    '<!DOCTYPE html>' \
    "<html lang=\"$MAIN\"><head><meta charset=\"utf-8\"><title>Redirect to $MAIN/</title>" \
    "<meta http-equiv=\"refresh\" content=\"0;URL='$MAIN/'\"><link rel=\"canonical\" href=\"$MAIN/\"></head>" \
    '<body></body></html>' \
    > "$OUTPUT_DIR/index.html"
  echo "build_all_chapters.sh: assembled $OUTPUT_DIR (languages=${RENDER_LANGS[*]}, images/ copied, root redirects to $MAIN/)"
fi

# --- The language-switcher pass ---------------------------------------------
# This pass runs once, over the FULLY ASSEMBLED tree, in the common image. It
# is a step for the whole book, not for one chapter (see COMMON_IMAGE above).
# languages.yml is mounted read-only next to the site. The pass reads the
# language list and the dropdown labels from it, and does not write to it.
#
# --no-inject skips this pass. A caller that splits the languages across
# machines MUST use --no-inject. inject_language_links.R is NOT idempotent:
# add_dropdown_links() adds to an existing <ul id="languages-links"> and does
# not make a new one. A pass for each language and then a pass over the
# assembled site thus ADD a second set of links to every page. Run the pass
# once only, over the complete tree.
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

# --- Remove the workspace ----------------------------------------------------
# Only a successful build gets to this point, so a failed build keeps its
# workspace for inspection. The render containers run as root and write
# files that root owns into the workspace, so a container removes them. The
# output is complete by now, so a failed removal is a warning, not a failure.
if ! docker run --rm -v "$WORK_ROOT:/w" "$COMMON_IMAGE" find /w -mindepth 1 -delete \
    || ! rmdir "$WORK_ROOT"; then
  echo "::warning::build_all_chapters.sh: could not remove the workspace $WORK_ROOT" >&2
fi
rm -f "$MANIFEST_FILE"

echo "build_all_chapters.sh: done -- $OUTPUT_DIR is ready to publish"
