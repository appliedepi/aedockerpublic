#!/usr/bin/env python3
# generate.py -- Phase 5a generator: splits the epiRhandbook monolith into a
# shared `epirhandbook-common` image plus thin per-chapter images, on the
# FROZEN 4.3.2 package stack (renv.lock does not move; see ../2.5/README.md
# "Phase 5a" for the design this implements).
#
# INPUTS (read-only; ../2.5 is sealed, never written):
#   ../2.5/chapters/footprints.tsv  -- per-chapter loadedNamespaces() dumps
#                                      from Phase 3 (52 chapters with >=1
#                                      executable R chunk).
#   ../2.5/renv.lock                -- the 473-package pin set (unchanged).
#
# METHOD
# 1. COMMON SET: for every package name, count how many of the 52 chapters'
#    footprints contain it. A package is "common" if that count is >=
#    COMMON_THRESHOLD. The threshold (38) is not an arbitrary round number --
#    it sits at the natural break in the frequency distribution: 65 packages
#    cluster at counts 38-52, then the NEXT most-frequent package drops to 26
#    (a gap of 12, versus gaps of at most 2 within the 38-52 cluster itself).
#    See frequency.tsv (this script's own output) for the full distribution.
#    10 of the 65 are base-R packages (base, compiler, datasets, grDevices,
#    graphics, grid, methods, stats, tools, utils) that ship with R itself --
#    they need no installing and are dropped before closure-expansion. The
#    other 55 are real renv.lock packages.
# 2. PER-CHAPTER FOOTPRINT: each target chapter's own footprints.tsv row,
#    filtered to renv.lock package names (dropping the same base-R names).
#    This is "the chapter's full footprint" the brief specifies as the
#    per-chapter delta -- not footprint-minus-common; see chapters/<ch>/Dockerfile's
#    own header for why installing the FULL footprint on top of common (not a
#    pre-subtracted delta) is what makes pak's own already-installed-package
#    skip do the "thin image" work, rather than this script doing it by hand.
# 3. CLOSURE EXPANSION: neither the common set nor a chapter's footprint is,
#    on its own, sufficient to INSTALL from source with pak's
#    dependencies=FALSE (required -- see pak_install_subset.R's header for
#    why dependencies=FALSE is non-negotiable here). A footprint is an
#    EMPIRICAL loadedNamespaces() record, not a declared dependency graph: it
#    can miss a build-time-only dependency (a compiled package's LinkingTo
#    header) that never shows up as a loaded namespace. So each target name
#    set is expanded to its full transitive closure over renv.lock's own
#    Requirements graph (Imports+Depends+LinkingTo, per renv/settings.json's
#    package.dependency.fields) -- the SAME graph epirhandbook/2.5/pak_install.R
#    already walks for the full 473-package install, just restricted to a
#    subset here. This is what makes "each chapter image ⊇ its footprint by
#    construction (dependency-closed)" true: the closure is a superset of the
#    footprint by construction (BFS only ever adds nodes), and the closure is
#    exactly what gets installed.
#
# OUTPUTS (all generated; do not hand-edit, rerun this script instead):
#   renv.lock                    -- byte-identical copy of ../2.5/renv.lock
#                                    (the build context must be self-contained
#                                    -- see README.md "Build context").
#   frequency.tsv                -- package, n_chapters_of_52, in_common
#   images.yaml                  -- the generated HALF of the one logical
#                                    catalog (Phase 4 schema). The planner is
#                                    given this file AND the hand-maintained
#                                    root images.yaml together: base edges cross
#                                    them (epirhandbook-common is FROM rbase, a
#                                    root row), so loading either alone makes the
#                                    base look like a typo and the plan dies.
#                                    Each row carries `renders` -- the .qmd that
#                                    image renders AT RUNTIME (it is mounted at
#                                    docker run; it is NOT a build input, nothing
#                                    .qmd is ever COPYed into the image). `dir`
#                                    is the separate, build-time relationship:
#                                    the context the image is built FROM.
#                                    validate_catalog ties renders' stem to dir's
#                                    basename AND to `name`, so neither the build
#                                    context nor the published name can drift
#                                    from the chapter actually rendered.
#   common/packages.txt          -- the common closure (install target)
#   common/Dockerfile
#   chapters/<chapter>/footprint.txt  -- that chapter's raw footprint,
#                                        filtered to renv.lock names (this IS
#                                        "each chapter's footprint list")
#   chapters/<chapter>/packages.txt   -- that chapter's closure (install target)
#   chapters/<chapter>/Dockerfile
#   A book chapter with NO footprints.tsv row (e.g. `errors`, a prose-only
#   page Phase 3 recorded zero loaded packages for) gets ONLY a bare
#   chapters/<chapter>/Dockerfile (FROM common, no delta) -- no footprint.txt
#   or packages.txt; its images.yaml row simply points `dir` at that bare
#   Dockerfile's directory, same as any other.
#
# DETERMINISM: every list is sorted before being written; there is no
# wall-clock, randomness, or filesystem-iteration-order dependency anywhere in
# this script. Re-running it against the same footprints.tsv/renv.lock
# reproduces byte-identical output (verified as part of this phase's
# acceptance check -- see the brief's "generate.py reproducibility check").
#
# SCOPE: the target chapter set is now the FULL catalog -- every book chapter
# Phase 3 compared (49 new_pages chapters + index = 50), read straight from
# ../2.5/chapters/results.tsv (read_scored_chapters: a row with a non-empty
# similarity_vs_book). The de-risk sample was a hard-coded 5-name list; that
# is replaced by deriving the set from Phase 3's own sealed output, so the
# generator reproduces exactly the chapters that were verified, with no
# hand-maintained list to drift. COMMON_THRESHOLD and the closure/frequency
# logic still run over ALL 52 footprints.tsv rows (the common set is a
# property of the WHOLE book, independent of which chapters get their own
# image), so nothing about the common-set derivation changed in the scale-up.

import csv
import hashlib
import json
import os
import sys
from collections import Counter, deque

HERE = os.path.dirname(os.path.abspath(__file__))
SEALED_2_5 = os.path.normpath(os.path.join(HERE, "..", "2.5"))
FOOTPRINTS_TSV = os.path.join(SEALED_2_5, "chapters", "footprints.tsv")
RESULTS_TSV = os.path.join(SEALED_2_5, "chapters", "results.tsv")
RENV_LOCK_SRC = os.path.join(SEALED_2_5, "renv.lock")

COMMON_THRESHOLD = 38  # see METHOD step 1 above; frequency.tsv shows the break

# --- Image naming (owner-decided; codified here, never typed into a build
# --- command) --------------------------------------------------------------
# common  : epirhandbook-common:2.6      (version lives ONLY in the tag)
# chapter : epirhandbook-<chapter>:2.6    (chapter in the NAME, version in the
#           TAG; source underscores kept, e.g. epirhandbook-tables_descriptive:2.6)
# The de-risk sample built images as epirhandbook-2.6-<chapter>:2.6 -- the
# version in BOTH the name and the tag. That is the stale scheme this
# generator replaces. generate.py emits images.yaml (the Phase 4 catalog) so
# the build reads every image name from a generated file rather than
# reconstructing "epirhandbook-<chapter>:2.6" by hand at the docker-build call
# site (the Phase 3/4 "no artifact without a committed generator that
# reproduces it" lesson, applied to the image name).
IMAGE_PREFIX = "epirhandbook"
IMAGE_TAG = "2.6"
BASE_IMAGE_RBASE = "rbase:4.3.2"
COMMON_IMAGE = f"{IMAGE_PREFIX}-common:{IMAGE_TAG}"


def chapter_image(chapter):
    """The full name:tag for a chapter's image -- the ONE place this string is
    constructed. epirhandbook-<chapter>:2.6, source underscores preserved.

    Docker repository names MUST be lowercase, but a chapter id may not be
    (`transition_to_R` has a capital R). Lowercasing here is what makes the tag
    valid AND keeps it consistent with Phase 4's own catalog NAME_RE
    (^[a-z0-9][a-z0-9._-]*$). The original-case chapter id is NOT lost: it is
    the basename of the image's `dir` (chapters/<Chapter>) in the generated
    images.yaml catalog -- so chapter<->image is recoverable from the one index
    with no second store. e.g. name=epirhandbook-transition_to_r:2.6,
    dir=.../chapters/transition_to_R."""
    return f"{IMAGE_PREFIX}-{chapter.lower()}:{IMAGE_TAG}"


# Repo-relative path of this generator's own directory -- the `dir` build
# context prefix for every row in the emitted images.yaml catalog.
CATALOG_DIR_PREFIX = f"epirhandbook/{IMAGE_TAG}"


def image_name(chapter):
    """The catalog `name` (image name WITHOUT the tag) for a chapter."""
    return chapter_image(chapter).rsplit(":", 1)[0]


def chapter_source_qmd(chapter):
    """The .qmd this chapter's image renders, relative to the handbook source
    root. `index` is index.qmd at the ROOT; every other book chapter is
    new_pages/<chapter>.qmd. This exception is exactly why the catalog states
    the source explicitly instead of deriving it from the chapter id."""
    return "index.qmd" if chapter == "index" else f"new_pages/{chapter}.qmd"


def read_footprints(path):
    """chapter -> sorted list of package names (as captured by Phase 3)."""
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            out[row["chapter"]] = sorted(row["packages"].split(","))
    return out


def read_scored_chapters(path):
    """The set of book chapters Phase 3 actually compared against the
    reference book render: every results.tsv row with a NON-empty
    similarity_vs_book. This is the authoritative 'every book chapter Phase 3
    compared' target set (49 new_pages chapters + index = 50) -- derived from
    Phase 3's own sealed results.tsv, never a hand-typed list that could drift
    out of sync with what was actually verified. The 18 non-book rows
    (part-divider stubs, under-construction stubs, render-failures like gis)
    have a blank similarity_vs_book and are excluded here -- they have no
    reference page to verify a per-chapter image against. Sorted for
    determinism."""
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["similarity_vs_book"].strip():
                out.append(row["chapter"])
    return sorted(out)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_closure(seed_names, pkgs):
    """BFS over renv.lock's own Requirements graph, restricted to names that
    are themselves real locked packages (base-R names like 'methods' are
    silently dropped, exactly as pak_install.R's own `deps` map does via
    `intersect(Requirements, names(pkgs))`). Returns a sorted list; the
    closure always contains every seed name (BFS only ever adds nodes), so
    the "image ⊇ footprint by construction" property holds by construction,
    not by a separately-checked invariant.
    """
    seed = set(n for n in seed_names if n in pkgs)
    seen = set(seed)
    q = deque(seed)
    while q:
        n = q.popleft()
        for r in pkgs[n].get("Requirements") or []:
            if r in pkgs and r not in seen:
                seen.add(r)
                q.append(r)
    return sorted(seen)


def write_lines(path, lines):
    with open(path, "w") as f:
        for line in lines:
            f.write(line + "\n")


DOCKERFILE_SYNTAX_HEADER = "# syntax=docker/dockerfile:1\n"

VERSION_LOAD_CHECK_R = (
    "R -e \""
    "lock <- jsonlite::fromJSON('renv.lock', simplifyVector = FALSE); "
    "pkgs <- lock[['Packages']]; "
    "targets <- readLines('packages.txt'); "
    "targets <- targets[nzchar(targets)]; "
    "bad <- character(0); "
    "for (n in targets) { "
    "if (!requireNamespace(n, quietly = TRUE)) { bad <- c(bad, paste0(n, ': FAILS TO LOAD')); next }; "
    "if (packageVersion(n) != pkgs[[n]][['Version']]) "
    "bad <- c(bad, sprintf('%s: installed %s != locked %s', n, as.character(packageVersion(n)), pkgs[[n]][['Version']])) "
    "}; "
    "if (length(bad)) { message('VERSION/LOAD CHECK FAILED (', length(bad), '):'); "
    "message(paste(bad, collapse = '\\n')); quit(status = 1L) }; "
    "message('VERSION/LOAD CHECK OK: all ', length(targets), ' target packages load at exact locked versions')"
    "\""
)


def common_dockerfile(n_raw_common, n_lock_installable, n_closure):
    return DOCKERFILE_SYNTAX_HEADER + f"""# epirhandbook-common:2.6 -- Phase 5a shared base for the per-chapter split.
# GENERATED by generate.py -- do not hand-edit; rerun generate.py instead.
#
# The common set: {n_raw_common} package names are loaded by >={COMMON_THRESHOLD} of the 52
# chapters in ../2.5/chapters/footprints.tsv (the natural break in the
# frequency distribution -- see frequency.tsv). {n_raw_common - n_lock_installable} of those are
# base-R packages (ship with R itself, nothing to install); the other
# {n_lock_installable} are real renv.lock packages (common/packages.txt, pre-closure).
# Closure-expanded over renv.lock's own Requirements graph (same graph
# ../2.5/pak_install.R already walks for the full 473 -- see
# pak_install_subset.R's header for why a footprint/common-set alone is not
# install-complete), this image's actual install target is {n_closure} packages
# -- common/packages.txt, post-closure, is what gets installed below.
#
# BASE_IMAGE mirrors epirhandbook/2.5/Dockerfile's own ARG pattern: a floating
# local tag by default, overridable to a digest pin once rbase is published
# to GHCR (Phase 4's first publish has not run yet, so there is no portable
# digest to pin against today -- see ../README.md "Build context" for why
# compute's own throwaway local-registry digest is deliberately NOT used
# here: it is host-specific, not a real published reference).
ARG BASE_IMAGE={BASE_IMAGE_RBASE}
FROM ${{BASE_IMAGE}}

WORKDIR /home/handbook

# --- pak + jsonlite bootstrap (identical to epirhandbook/2.5/Dockerfile) ----
# rbase carries no R packages at all; pak is the installer, jsonlite is
# needed (by this script AND pak_install_subset.R) to parse renv.lock.
RUN R -e "install.packages(c('pak', 'jsonlite'), repos = 'https://packagemanager.posit.co/cran/__linux__/jammy/latest'); stopifnot(packageVersion('pak') >= '0.11.0', requireNamespace('jsonlite', quietly = TRUE))"

COPY renv.lock renv.lock
COPY pak_install_subset.R pak_install_subset.R
COPY common/packages.txt packages.txt

# --- Install the common closure ({n_closure} packages) at exact renv.lock versions -
# GITHUB_PAT is a BuildKit SECRET (never ARG+ENV -- an ENV bakes the token
# into the image's Config.Env, where `docker inspect` leaks it; see
# ../2.5/README.md and PROJECT.md for the full rationale, unchanged here).
# The common set needs it: `tidyverse` (itself in the >={COMMON_THRESHOLD}-chapter common
# set) Imports `googlesheets4`, which this renv.lock pins from GitHub, not
# CRAN -- so even a CRAN-only-looking common set reaches GitHub once
# closure-expanded.
RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \\
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" Rscript pak_install_subset.R packages.txt \\
    && rm -rf /tmp/*

# --- Build-time invariant: every package in packages.txt LOADS and is at its
# --- EXACT locked version (same check as Phase 2's Dockerfile, restricted to
# --- this image's own target list rather than all 473) ---------------------
RUN {VERSION_LOAD_CHECK_R}
"""


def chapter_dockerfile(chapter, n_footprint, n_closure):
    return DOCKERFILE_SYNTAX_HEADER + f"""# {chapter_image(chapter)} -- Phase 5a per-chapter image.
# GENERATED by generate.py -- do not hand-edit; rerun generate.py instead.
#
# FROM the shared common image; installs THIS CHAPTER's own footprint
# (chapters/{chapter}/footprint.txt, {n_footprint} renv.lock packages, from
# ../2.5/chapters/footprints.tsv), closure-expanded to chapters/{chapter}/packages.txt
# ({n_closure} packages, the actual install target below). pak sees common's
# packages already present at the exact locked version and skips them --
# dependencies=FALSE never re-solves, so a skip is a true no-op, not a
# reinstall -- and only builds the delta. This is what makes the final image
# ⊇ the chapter's footprint BY CONSTRUCTION, without this Dockerfile (or
# generate.py) needing to reason about whether the common image's own 55/125
# packages are themselves a complete closure: whatever common is missing that
# THIS chapter's own closure needs, this RUN step installs it here instead.
ARG BASE_IMAGE={COMMON_IMAGE}
FROM ${{BASE_IMAGE}}

WORKDIR /home/handbook

COPY renv.lock renv.lock
COPY pak_install_subset.R pak_install_subset.R
COPY chapters/{chapter}/packages.txt packages.txt

RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \\
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" Rscript pak_install_subset.R packages.txt \\
    && rm -rf /tmp/*

# --- Build-time invariant, restricted to this chapter's own target list ----
RUN {VERSION_LOAD_CHECK_R}
"""


def bare_chapter_dockerfile(chapter):
    """A book chapter with NO row in footprints.tsv (Phase 3 captured zero
    loaded packages for it -- no executable R chunks, e.g. `errors`, a
    prose-only page). It has no per-chapter install delta: the image is
    epirhandbook-common:2.6 itself, re-tagged under the chapter's own name so
    every book chapter Phase 3 compared has a correspondingly-named image to
    render on. Nothing is installed on top of common; there is no packages.txt
    or footprint.txt and therefore no per-chapter version/load check (common's
    own build-time invariant already covers everything present)."""
    return DOCKERFILE_SYNTAX_HEADER + f"""# {chapter_image(chapter)} -- Phase 5a per-chapter image (NO delta).
# GENERATED by generate.py -- do not hand-edit; rerun generate.py instead.
#
# This chapter has NO row in ../2.5/chapters/footprints.tsv: Phase 3 recorded
# zero loaded packages for it (no executable R chunks). It needs nothing on
# top of common, so this image IS epirhandbook-common:2.6, re-tagged under the
# chapter's own name -- present only so every book chapter Phase 3 compared
# has a correspondingly-named per-chapter image (its images.yaml row points at
# this bare Dockerfile, same as any other chapter).
ARG BASE_IMAGE={COMMON_IMAGE}
FROM ${{BASE_IMAGE}}

WORKDIR /home/handbook
"""


def main():
    footprints = read_footprints(FOOTPRINTS_TSV)
    n_chapters_total = len(footprints)

    # Every book chapter Phase 3 compared (49 new_pages + index = 50), derived
    # from the sealed results.tsv -- NOT a hand-maintained list. See
    # read_scored_chapters. A chapter here with no footprints.tsv row (e.g.
    # `errors`) gets a bare FROM-common image (bare_chapter_dockerfile).
    target_chapters = read_scored_chapters(RESULTS_TSV)

    lock = json.load(open(RENV_LOCK_SRC))
    pkgs = lock["Packages"]

    # --- frequency + common set ---------------------------------------------
    freq = Counter()
    for names in footprints.values():
        for p in names:
            freq[p] += 1

    common_raw = sorted(p for p, c in freq.items() if c >= COMMON_THRESHOLD)
    common_lock_names = sorted(p for p in common_raw if p in pkgs)
    common_closure = compute_closure(common_lock_names, pkgs)

    # --- write renv.lock copy (self-contained build context) ---------------
    out_lock = os.path.join(HERE, "renv.lock")
    with open(RENV_LOCK_SRC, "rb") as src, open(out_lock, "wb") as dst:
        dst.write(src.read())
    assert sha256_file(out_lock) == sha256_file(RENV_LOCK_SRC), (
        "renv.lock copy does not match ../2.5/renv.lock byte-for-byte"
    )

    # --- write frequency.tsv (transparency: the distribution cited in README) ---
    freq_path = os.path.join(HERE, "frequency.tsv")
    with open(freq_path, "w") as f:
        f.write("package\tn_chapters\tof_52\tin_common\n")
        for p, c in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
            f.write(f"{p}\t{c}\t{n_chapters_total}\t{'yes' if c >= COMMON_THRESHOLD else 'no'}\n")

    # --- common/ -------------------------------------------------------------
    common_dir = os.path.join(HERE, "common")
    os.makedirs(common_dir, exist_ok=True)
    write_lines(os.path.join(common_dir, "packages.txt"), common_closure)
    with open(os.path.join(common_dir, "Dockerfile"), "w") as f:
        f.write(common_dockerfile(len(common_raw), len(common_lock_names), len(common_closure)))

    # --- chapters/<chapter>/ (every book chapter Phase 3 compared) ----------
    chapters_dir = os.path.join(HERE, "chapters")
    summary = []
    no_footprint = []          # book chapters with no footprints.tsv row
    # catalog rows for images.yaml -- the ONE index (Phase 4 catalog schema).
    # No separate manifest.tsv: the chapter<->image linkage is inherent in each
    # row (name is the lowercased image, dir's basename is the original-case
    # chapter), so it lives in exactly one generated place. Row 0 is common (the
    # shared base every chapter builds FROM); the rest are chapters, sorted.
    catalog = [{
        "name": f"{IMAGE_PREFIX}-common",
        "dir": f"{CATALOG_DIR_PREFIX}/common",
        "context": CATALOG_DIR_PREFIX,
        "base": BASE_IMAGE_RBASE,
    }]
    for chapter in target_chapters:
        ch_dir = os.path.join(chapters_dir, chapter)
        os.makedirs(ch_dir, exist_ok=True)

        if chapter not in footprints:
            # No footprint row -> bare image FROM common, no install delta.
            # Write ONLY the Dockerfile (no footprint.txt / packages.txt).
            with open(os.path.join(ch_dir, "Dockerfile"), "w") as f:
                f.write(bare_chapter_dockerfile(chapter))
            no_footprint.append(chapter)
            catalog.append({
                "name": image_name(chapter),
                "renders": chapter_source_qmd(chapter),
                "dir": f"{CATALOG_DIR_PREFIX}/chapters/{chapter}",
                "context": CATALOG_DIR_PREFIX,
                "base": COMMON_IMAGE,
            })
            summary.append({
                "chapter": chapter,
                "raw_footprint_n": 0,
                "footprint_lock_n": 0,
                "own_closure_n": 0,
                "delta_over_common_n": 0,
                "final_image_pkg_n": len(common_closure),
            })
            continue

        raw_footprint = footprints[chapter]
        footprint_lock_names = sorted(p for p in raw_footprint if p in pkgs)
        closure = compute_closure(footprint_lock_names, pkgs)

        write_lines(os.path.join(ch_dir, "footprint.txt"), footprint_lock_names)
        write_lines(os.path.join(ch_dir, "packages.txt"), closure)
        with open(os.path.join(ch_dir, "Dockerfile"), "w") as f:
            f.write(chapter_dockerfile(chapter, len(footprint_lock_names), len(closure)))

        catalog.append({
            "name": image_name(chapter),
            "renders": chapter_source_qmd(chapter),
            "dir": f"{CATALOG_DIR_PREFIX}/chapters/{chapter}",
            "context": CATALOG_DIR_PREFIX,
            "base": COMMON_IMAGE,
        })
        summary.append({
            "chapter": chapter,
            "raw_footprint_n": len(raw_footprint),
            "footprint_lock_n": len(footprint_lock_names),
            "own_closure_n": len(closure),
            "delta_over_common_n": len(set(closure) - set(common_closure)),
            "final_image_pkg_n": len(set(closure) | set(common_closure)),
        })

    # --- images.yaml: the ONE index for the 2.6 family, in Phase 4 catalog
    # schema so the Phase 4 planner consumes it directly (no bespoke manifest,
    # no second store). Every image appears exactly once. The chapter<->image
    # linkage needs no dedicated field: `name` is the lowercased image and the
    # basename of `dir` is the original-case chapter (e.g.
    # name: epirhandbook-transition_to_r / dir: .../chapters/transition_to_R).
    # GENERATED -- hand-edit footprints.tsv or generate.py, never this file.
    catalog_path = os.path.join(HERE, "images.yaml")
    with open(catalog_path, "w") as f:
        f.write("# GENERATED by generate.py -- do not hand-edit; rerun generate.py.\n")
        f.write("# The 2.6 per-chapter split catalog (Phase 4 schema). Per chapter row:\n")
        f.write("#   renders -- the .qmd rendered AT RUNTIME (mounted at docker run; it\n")
        f.write("#              is never COPYed into the image)\n")
        f.write("#   dir     -- this image's own files: change-detection scope, and where\n")
        f.write("#              its Dockerfile lives\n")
        f.write("#   context -- the docker build context, i.e. the root COPY resolves\n")
        f.write("#              against (epirhandbook/2.6, NOT the chapter dir -- building\n")
        f.write("#              with the chapter dir as context fails: renv.lock and\n")
        f.write("#              pak_install_subset.R are outside it)\n")
        f.write("#   name    -- that chapter lowercased for Docker (a registry constraint,\n")
        f.write("#              applied only here)\n")
        f.write("# validate_catalog ties renders' stem to BOTH dir's basename and name, and\n")
        f.write("# requires dir to live inside context. Consumers read the image name from\n")
        f.write("# `name` -- never reconstruct it. common is row 0.\n")
        f.write("images:\n")
        for row in catalog:
            f.write(f"  - name: {row['name']}\n")
            if "renders" in row:
                f.write(f"    renders: {row['renders']}\n")
            f.write(f"    dir: {row['dir']}\n")
            if "context" in row:
                f.write(f"    context: {row['context']}\n")
            f.write(f"    tags: [\"{IMAGE_TAG}\"]\n")
            base = "null" if row["base"] is None else f"\"{row['base']}\""
            f.write(f"    base: {base}\n")
            f.write(f"    base_digest: null\n")
            f.write(f"    live: true\n")
            f.write(f"    frozen: true\n")

    # --- stdout summary (audit trail; also the reproducibility check reads this) ---
    print(f"chapters in footprints.tsv: {n_chapters_total}")
    print(f"book chapters Phase 3 compared (target set): {len(target_chapters)}")
    print(f"  of those, WITH a footprint row (delta image): {len(target_chapters) - len(no_footprint)}")
    print(f"  of those, NO footprint row (bare common image): {len(no_footprint)}"
          + (f" -> {', '.join(no_footprint)}" if no_footprint else ""))
    print(f"COMMON_THRESHOLD: {COMMON_THRESHOLD}")
    print(f"common: raw names >= threshold (incl. base-R) = {len(common_raw)}")
    print(f"common: renv.lock-installable (pre-closure)    = {len(common_lock_names)}")
    print(f"common: closure-expanded install target        = {len(common_closure)}")
    print()
    print("chapter\traw_footprint\tfootprint&lock\town_closure\tdelta_over_common\tfinal_image_pkgs")
    for s in summary:
        print(f"{s['chapter']}\t{s['raw_footprint_n']}\t{s['footprint_lock_n']}\t"
              f"{s['own_closure_n']}\t{s['delta_over_common_n']}\t{s['final_image_pkg_n']}")
    print()
    print(f"-> {out_lock}")
    print(f"-> {freq_path}")
    print(f"-> {catalog_path}")
    print(f"-> {os.path.join(common_dir, 'packages.txt')}")
    print(f"-> {os.path.join(common_dir, 'Dockerfile')}")
    print(f"-> chapters/<chapter>/ for {len(target_chapters)} chapters "
          f"({len(target_chapters) - len(no_footprint)} with footprint.txt+packages.txt+Dockerfile, "
          f"{len(no_footprint)} bare Dockerfile only)")


if __name__ == "__main__":
    main()
