#!/usr/bin/env python3
# generate.py -- Phase 5b generator: splits the epiRhandbook monolith into a
# shared `epirhandbook-common` image plus thin per-chapter images, on the
# 2026 package stack (R 4.6.0 / rbase:4.6.0). Adapted from
# epirhandbook/2.6/generate.py, which does the SAME split on the FROZEN 2024
# stack (R 4.3.2) -- read that file's header for the method in full; this
# header only calls out what 2.7 changes.
#
# INSTALL MODEL: there is NO pre-computed dependency closure. pak resolves
# the full dependency tree itself (dependencies = NA) against the
# immutable dated CRAN/Bioc snapshot at build time, so each image only needs
# to state its own MAIN packages (the chapter's empirical footprint) --
# pak_install_subset.R's own header spells out the two-input interface this
# script targets, and why a hand-computed closure is unnecessary once pak is
# doing the resolving against a snapshot that never moves.
#
# INPUTS (read-only; nothing here is written back):
#   footprints.tsv            -- per-chapter loadedNamespaces() dumps,
#                                 re-measured on the 2026 stack (48 chapters
#                                 with >=1 executable R chunk).
#   packages_github.json      -- the 8 GitHub-pinned packages (name -> commit
#                                 SHA). ALREADY EXISTS for 2.7; generate.py
#                                 only reads the 8 package NAMES from it, to
#                                 exclude them from every packages_cran.txt
#                                 (they install from their SHA pin, not by
#                                 bare name off the snapshot). Never
#                                 regenerated here.
#   verify_render_26.04.tsv    -- chapter, rc (the forward-port's per-chapter
#                                 render verification). The 49 rows with
#                                 rc == 0 are the chapter set that gets an
#                                 image -- 2.6's equivalent input was a
#                                 Phase-3 results.tsv keyed on a non-empty
#                                 similarity_vs_book; 2.7 has no reference-
#                                 book comparison to key on, so the render
#                                 return code is the verification signal
#                                 instead.
#
# METHOD:
# 1. COMMON SET: for every package name, count how many of the 48 chapters'
#    footprints contain it. A package is "common" if that count is >=
#    COMMON_THRESHOLD. The threshold (34) is, as in 2.6, the natural break in
#    the frequency distribution -- NOT 2.6's 38 copied blindly: 66 packages
#    cluster at counts 34-48, then the NEXT most-frequent package drops to 22
#    -- a gap of 12, the single largest gap anywhere in the sorted
#    per-package counts (see frequency.tsv for the full distribution). 10 of
#    the 66 are BASE_R_PACKAGES (base, compiler, datasets, grDevices,
#    graphics, grid, methods, stats, tools, utils) that ship with R itself --
#    they need no installing and are dropped before packages_cran.txt is
#    written. The other 56 are real installable names.
# 2. PER-CHAPTER FOOTPRINT: each target chapter's own footprints.tsv row,
#    minus BASE_R_PACKAGES. Installing the FULL footprint on top of common
#    (not a pre-subtracted delta) is what makes pak's own
#    already-installed-package skip do the "thin image" work -- see
#    pak_install_subset.R's own header for why.
# 3. CRAN/GITHUB SPLIT: each name set from steps 1-2 is a mix of ordinary
#    CRAN/Bioc names (install by bare name) and, rarely, one of the 8
#    GitHub-pinned names (packages_github.json), which need their commit SHA
#    instead. So those 8 names are excluded from packages_cran.txt and left
#    for packages_github.json to supply. THAT IS THE ENTIRE SPLIT: no
#    dependency closure is computed over either set -- pak_install_subset.R
#    hands pak the bare names in packages_cran.txt (plus
#    packages_github.json's SHAs, common only) and lets pak resolve
#    (dependencies = NA) whatever else each package needs, against the
#    immutable dated snapshot. A footprint is an EMPIRICAL
#    loadedNamespaces() record, not a declared dependency graph: exactly the
#    right input for "what must load", and the wrong one to hand-expand for
#    "what must install" -- that expansion is pak's job now, not this
#    script's.
#
# OUTPUTS (all generated; do not hand-edit, rerun this script instead):
#   frequency.tsv                -- package, n_chapters_of_48, in_common
#   images.yaml                  -- the generated HALF of the one logical
#                                    catalog (Phase 4 schema). See 2.6's own
#                                    images.yaml header for the field
#                                    meanings (renders/dir/context/name) --
#                                    they carry over unchanged.
#   common/packages_cran.txt     -- the common set's CRAN/Bioc install list
#                                    (bare names; no closure)
#   common/Dockerfile             -- also COPYs the already-existing
#                                    packages_github.json and
#                                    common/build_chapter.sh (this script
#                                    writes neither file, only the COPY of
#                                    them)
#   chapters/<chapter>/footprint.txt      -- that chapter's raw footprint,
#                                            minus BASE_R_PACKAGES
#   chapters/<chapter>/packages_cran.txt  -- that chapter's own CRAN/Bioc
#                                            install list (footprint.txt
#                                            minus the 8 GitHub names)
#   chapters/<chapter>/Dockerfile
#   A book chapter with NO footprints.tsv row (`errors`, same as in 2.6) gets
#   ONLY a bare chapters/<chapter>/Dockerfile (FROM common, no delta) -- no
#   footprint.txt or packages_cran.txt.
#
# SCOPE: the target chapter set is read straight from
# verify_render_26.04.tsv's own rc==0 rows (read_verified_chapters) -- not a
# hand-maintained list, so the generator reproduces exactly the chapters the
# forward-port verified render cleanly, with nothing to drift out of sync.
# `epidemic_models` is cut from 2.7; it is asserted absent from the target
# set below rather than special-cased, because it simply is not an rc==0
# row. COMMON_THRESHOLD and the frequency logic run over ALL 48
# footprints.tsv rows, independent of which chapters end up in the target
# set -- same as 2.6.
#
# DETERMINISM: every list is sorted before being written; there is no
# wall-clock, randomness, or filesystem-iteration-order dependency anywhere
# in this script. Re-running it against the same footprints.tsv /
# packages_github.json / verify_render_26.04.tsv reproduces byte-identical
# output.

import csv
import json
import os
from collections import Counter

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
FOOTPRINTS_TSV = os.path.join(HERE, "footprints.tsv")
PACKAGES_GITHUB_JSON = os.path.join(HERE, "packages_github.json")
VERIFY_RENDER_TSV = os.path.join(HERE, "verify_render_26.04.tsv")
ROOT_CATALOG = os.path.join(HERE, "..", "..", "images.yaml")

COMMON_THRESHOLD = 34  # see METHOD step 1 above; frequency.tsv shows the break

# The 10 base-R packages that ship with R itself. They show up in every
# footprint's loadedNamespaces() dump (base, methods, stats, ... are always
# loaded) but need no installing. Formerly dropped implicitly via "is this
# name in manifest.json's Packages dict"; manifest.json is gone (there is no
# closure to expand any more), so this is now the explicit, hardcoded filter.
BASE_R_PACKAGES = frozenset({
    "base", "compiler", "datasets", "grDevices", "graphics", "grid",
    "methods", "stats", "tools", "utils",
})


def rbase_ref_from_root_catalog():
    """The single source of truth for the dated CRAN snapshot is the rbase
    image TAG in the root images.yaml (build_image.sh derives the snapshot URL
    from its YYYY-MM-DD suffix). generate.py READS that tag here rather than
    re-typing the date, so the 2.7 common image is FROM the exact same ref and
    the date is defined in exactly one place. Move the date = edit the root
    catalog's rbase tag; nothing here changes."""
    with open(ROOT_CATALOG) as f:
        catalog = yaml.safe_load(f)
    rbase = next(img for img in catalog["images"] if img["name"] == "rbase")
    tags = rbase["tags"]
    assert len(tags) == 1, f"expected exactly one rbase tag in {ROOT_CATALOG}, got {tags}"
    return f"rbase:{tags[0]}"


# --- Image naming (owner-decided; codified here, never typed into a build
# --- command) --------------------------------------------------------------
# common  : epirhandbook-common:2.7      (version lives ONLY in the tag)
# chapter : epirhandbook-<chapter>:2.7    (chapter in the NAME, version in the
#           TAG; source underscores kept, e.g. epirhandbook-tables_descriptive:2.7)
# generate.py emits images.yaml (the Phase 4 catalog) so the build reads
# every image name from a generated file rather than reconstructing
# "epirhandbook-<chapter>:2.7" by hand at the docker-build call site.
IMAGE_PREFIX = "epirhandbook"
IMAGE_TAG = "2.7"
BASE_IMAGE_RBASE = rbase_ref_from_root_catalog()  # derived, never hardcoded
COMMON_IMAGE = f"{IMAGE_PREFIX}-common:{IMAGE_TAG}"


def chapter_image(chapter):
    """The full name:tag for a chapter's image -- the ONE place this string is
    constructed. epirhandbook-<chapter>:2.7, source underscores preserved.

    Docker repository names MUST be lowercase, but a chapter id may not be
    (`transition_to_R` has a capital R). Lowercasing here is what makes the tag
    valid AND keeps it consistent with Phase 4's own catalog NAME_RE
    (^[a-z0-9][a-z0-9._-]*$). The original-case chapter id is NOT lost: it is
    the basename of the image's `dir` (chapters/<Chapter>) in the generated
    images.yaml catalog -- so chapter<->image is recoverable from the one index
    with no second store. e.g. name=epirhandbook-transition_to_r:2.7,
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
    """chapter -> sorted list of package names (re-measured on the 2026 stack)."""
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            out[row["chapter"]] = sorted(row["packages"].split(","))
    return out


def read_verified_chapters(path):
    """The set of book chapters the forward-port verified render cleanly on
    the 2026 stack: every verify_render_26.04.tsv row with rc == 0. This is
    the authoritative "every chapter that gets an image" target set (49
    rows) -- derived from the forward-port's own sealed verification output,
    never a hand-typed list that could drift out of sync with what was
    actually verified. Sorted for determinism."""
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["rc"].strip() == "0":
                out.append(row["chapter"])
    return sorted(out)


def read_github_pin_names(path):
    """The 8 GitHub-pinned package NAMES -- packages_github.json's own
    GitHubPins keys. generate.py excludes these from every packages_cran.txt:
    they install from the commit SHA packages_github.json carries for them
    (read directly by pak_install_subset.R at build time), not by bare name
    off the dated CRAN/Bioc snapshot. This file ALREADY EXISTS for 2.7;
    generate.py only ever reads it here, never writes it, and never reads a
    Requirements field from it -- there isn't one, these are leaf pins with a
    SHA, not a dependency graph."""
    with open(path) as f:
        pins = json.load(f)["GitHubPins"]
    return frozenset(pins.keys())


def installable_subset(names):
    """A raw name set (a chapter's footprint, or the common set's raw names),
    minus BASE_R_PACKAGES. This is what footprint.txt records: every
    non-base-R name the chapter actually loads, GitHub-pinned names included
    -- footprint.txt is provenance for what loads, not an install list.
    cran_subset, below, is the install list, and also drops the GitHub
    names. Sorted for determinism."""
    return sorted(n for n in names if n not in BASE_R_PACKAGES)


def cran_subset(names, github_names):
    """installable_subset(names), minus github_names too -- the CRAN/Bioc
    install list packages_cran.txt holds: bare names pak installs directly
    off the dated snapshot. github_names are excluded because they install
    from their commit SHA in packages_github.json instead (read directly by
    pak_install_subset.R), not by bare name. NO closure, NO dependency
    expansion -- pak resolves everything else itself (dependencies = NA)."""
    return sorted(n for n in installable_subset(names) if n not in github_names)


def write_lines(path, lines):
    with open(path, "w") as f:
        for line in lines:
            f.write(line + "\n")


DOCKERFILE_SYNTAX_HEADER = "# syntax=docker/dockerfile:1\n"

# Build-time invariant: every target package LOADS. It does NOT assert a
# version -- the dated PPM snapshot (owned by rbase's Rprofile.site) is the
# single source of truth for which version each name resolves to. Asserting a
# version here would be a SECOND source that can only ever agree with the date
# or contradict it; when it contradicts (as a stale pak floor once did), it is
# the assertion that is wrong, not the snapshot. So the check confirms the
# install succeeded (the package is present and loadable), nothing more.
LOAD_CHECK_R = (
    "R -e \""
    "targets <- readLines('packages_cran.txt'); "
    "targets <- targets[nzchar(targets)]; "
    "bad <- targets[!vapply(targets, requireNamespace, logical(1), quietly = TRUE)]; "
    "if (length(bad)) { message('LOAD CHECK FAILED (', length(bad), '): ', paste(bad, collapse = ', ')); quit(status = 1L) }; "
    "message('LOAD CHECK OK: all ', length(targets), ' target packages load')"
    "\""
)


def common_dockerfile(n_raw_common, n_installable, n_cran):
    return DOCKERFILE_SYNTAX_HEADER + f"""# epirhandbook-common:2.7 -- Phase 5b shared base for the per-chapter split,
# on the 2026 package stack. GENERATED by generate.py -- do not hand-edit;
# rerun generate.py instead.
#
# The common set: {n_raw_common} package names are loaded by >={COMMON_THRESHOLD} of the 48
# chapters in footprints.tsv (the natural break in the frequency distribution
# -- see frequency.tsv). {n_raw_common - n_installable} of those are BASE_R_PACKAGES (ship
# with R itself, nothing to install); the other {n_installable} are real installable
# names. common/packages_cran.txt ({n_cran} names) is that {n_installable}, minus
# whichever of the 8 GitHub-pinned names (packages_github.json) happen to also
# be common -- packages_github.json supplies those separately. NO closure: pak
# resolves the hard dependencies itself (dependencies = NA -- not Suggests) against the
# immutable dated snapshot below.
#
# BASE_IMAGE mirrors epirhandbook/2.6/common/Dockerfile's own ARG pattern: a
# floating local tag by default, overridable to a digest pin once rbase:4.6.0
# is published to GHCR (see root images.yaml's digest-pinning procedure).
ARG BASE_IMAGE={BASE_IMAGE_RBASE}
FROM ${{BASE_IMAGE}}

WORKDIR /home/handbook

# --- pak + jsonlite + BiocManager bootstrap ---------------------------------
# rbase:4.6.0 carries no R packages at all. pak is the installer; jsonlite is
# needed (by this script AND pak_install_subset.R) to parse JSON; BiocManager
# supplies BiocManager::version() -- the R-paired Bioconductor release,
# derived from the R version rather than stored anywhere as a second source.
# NO repos= and NO version floor: rbase's Rprofile.site already pins the dated
# PPM snapshot as the default repo, and THAT date is the single source of
# truth for every version. install.packages() inherits it; asserting a pak
# version here would be a second source that can only agree with the date or
# contradict it (a copied `>= 0.11.0` floor once did -- the snapshot pins pak
# 0.10.0, which the discovery build installed 468 packages with). If a newer
# package is ever needed, move rbase's snapshot date -- never assert a version.
RUN R -e "install.packages(c('pak', 'jsonlite', 'BiocManager')); stopifnot(requireNamespace('pak', quietly = TRUE), requireNamespace('jsonlite', quietly = TRUE), requireNamespace('BiocManager', quietly = TRUE))"

COPY packages_github.json packages_github.json
COPY pak_install_subset.R pak_install_subset.R
COPY common/packages_cran.txt packages_cran.txt

# --- Install the common set's {n_cran} CRAN/Bioc names + all 8 GitHub pins,
# --- then let pak resolve hard dependencies (dependencies = NA -- Depends/Imports/LinkingTo, not Suggests) against the
# --- immutable dated snapshot -- NO pre-computed closure --------------------
# GITHUB_PAT is a BuildKit SECRET (never ARG+ENV -- an ENV bakes the token
# into the image's Config.Env, where `docker inspect` leaks it). common is the
# ONE image that installs all 8 GitHub pins (via packages_github.json): every
# chapter image is FROM common, so every chapter inherits them, and a
# transitive pull anywhere downstream resolves to the pinned commit rather
# than re-resolving the package from CRAN.
RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \\
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" \\
    Rscript pak_install_subset.R packages_cran.txt packages_github.json \\
    && rm -rf /tmp/*

# --- The render entrypoint every chapter image inherits (FROM common) -------
# common/build_chapter.sh ALREADY EXISTS -- not generated here, just
# installed onto PATH so every chapter image can call it by name.
COPY common/build_chapter.sh /usr/local/bin/build_chapter.sh
RUN chmod +x /usr/local/bin/build_chapter.sh

# --- Build-time invariant: every package in packages_cran.txt LOADS --------
RUN {LOAD_CHECK_R}
"""


def chapter_dockerfile(chapter, n_footprint, n_cran):
    return DOCKERFILE_SYNTAX_HEADER + f"""# {chapter_image(chapter)} -- Phase 5b per-chapter image.
# GENERATED by generate.py -- do not hand-edit; rerun generate.py instead.
#
# FROM the shared common image (BiocManager already present there -- no
# re-bootstrap here). Installs THIS CHAPTER's own footprint
# (chapters/{chapter}/footprint.txt, {n_footprint} names, footprint minus
# BASE_R_PACKAGES) as chapters/{chapter}/packages_cran.txt ({n_cran} names,
# footprint.txt minus the 8 GitHub-pinned names -- common already installed
# those and this image inherits them, so there is no packages_github.json
# here). pak sees common's packages already present and skips them --
# dependencies = NA only resolves what's missing, so installing this
# chapter's FULL footprint on top of common (not a pre-subtracted delta) is
# what makes the final image a strict superset of the footprint BY
# CONSTRUCTION, with no hand-computed closure anywhere in this build.
ARG BASE_IMAGE={COMMON_IMAGE}
FROM ${{BASE_IMAGE}}

WORKDIR /home/handbook

COPY pak_install_subset.R pak_install_subset.R
COPY chapters/{chapter}/packages_cran.txt packages_cran.txt

RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \\
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" \\
    Rscript pak_install_subset.R packages_cran.txt \\
    && rm -rf /tmp/*

# --- Build-time invariant, restricted to this chapter's own target list ----
RUN {LOAD_CHECK_R}
"""


def bare_chapter_dockerfile(chapter):
    """A book chapter with NO row in footprints.tsv (the 2026 re-measurement
    recorded zero loaded packages for it -- no executable R chunks, e.g.
    `errors`, a prose-only page). It has no per-chapter install delta: the
    image is epirhandbook-common:2.7 itself, re-tagged under the chapter's
    own name so every verified chapter has a correspondingly-named image to
    render on. Nothing is installed on top of common; there is no
    packages_cran.txt or footprint.txt and therefore no per-chapter
    load check (common's own build-time invariant already covers everything
    present)."""
    return DOCKERFILE_SYNTAX_HEADER + f"""# {chapter_image(chapter)} -- Phase 5b per-chapter image (NO delta).
# GENERATED by generate.py -- do not hand-edit; rerun generate.py instead.
#
# This chapter has NO row in footprints.tsv: the 2026 re-measurement recorded
# zero loaded packages for it (no executable R chunks). It needs nothing on
# top of common, so this image IS epirhandbook-common:2.7, re-tagged under the
# chapter's own name -- present only so every verified chapter has a
# correspondingly-named per-chapter image (its images.yaml row points at
# this bare Dockerfile, same as any other chapter).
ARG BASE_IMAGE={COMMON_IMAGE}
FROM ${{BASE_IMAGE}}

WORKDIR /home/handbook
"""


def main():
    footprints = read_footprints(FOOTPRINTS_TSV)
    n_chapters_total = len(footprints)

    # Every chapter the forward-port verified renders cleanly (49), derived
    # from the sealed verify_render_26.04.tsv -- NOT a hand-maintained list.
    # See read_verified_chapters. A chapter here with no footprints.tsv row
    # (`errors`) gets a bare FROM-common image (bare_chapter_dockerfile).
    target_chapters = read_verified_chapters(VERIFY_RENDER_TSV)
    assert "epidemic_models" not in target_chapters, (
        "epidemic_models is expected to be cut from 2.7 (absent from "
        "verify_render_26.04.tsv's rc=0 rows) -- found it in the target "
        "chapter set instead."
    )

    # The 8 GitHub-pinned names, excluded from every packages_cran.txt below
    # (packages_github.json supplies them instead, common only). Read-only:
    # generate.py never regenerates this file.
    github_names = read_github_pin_names(PACKAGES_GITHUB_JSON)
    assert len(github_names) == 8, (
        f"expected exactly 8 GitHub-pinned names in {PACKAGES_GITHUB_JSON}, "
        f"got {len(github_names)}: {sorted(github_names)}"
    )

    # No CRAN-snapshot URL is read here: rbase's Rprofile.site owns the dated
    # snapshot (the single source of truth for versions), and the generated
    # Dockerfiles inherit it -- generate.py never re-types or re-asserts it.

    # --- frequency + common set ---------------------------------------------
    freq = Counter()
    for names in footprints.values():
        for p in names:
            freq[p] += 1

    common_raw = sorted(p for p, c in freq.items() if c >= COMMON_THRESHOLD)
    common_installable = installable_subset(common_raw)
    common_cran = cran_subset(common_raw, github_names)

    # --- write frequency.tsv (transparency: the distribution cited above) ---
    freq_path = os.path.join(HERE, "frequency.tsv")
    with open(freq_path, "w") as f:
        f.write(f"package\tn_chapters\tof_{n_chapters_total}\tin_common\n")
        for p, c in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0])):
            f.write(f"{p}\t{c}\t{n_chapters_total}\t{'yes' if c >= COMMON_THRESHOLD else 'no'}\n")

    # --- common/ -------------------------------------------------------------
    common_dir = os.path.join(HERE, "common")
    os.makedirs(common_dir, exist_ok=True)
    write_lines(os.path.join(common_dir, "packages_cran.txt"), common_cran)
    with open(os.path.join(common_dir, "Dockerfile"), "w") as f:
        f.write(common_dockerfile(len(common_raw), len(common_installable), len(common_cran)))

    # --- chapters/<chapter>/ (every chapter the forward-port verified) ------
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
            # Write ONLY the Dockerfile (no footprint.txt / packages_cran.txt).
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
                "footprint_n": 0,
                "packages_cran_n": 0,
            })
            continue

        raw_footprint = footprints[chapter]
        footprint_installable = installable_subset(raw_footprint)
        packages_cran = cran_subset(raw_footprint, github_names)

        write_lines(os.path.join(ch_dir, "footprint.txt"), footprint_installable)
        write_lines(os.path.join(ch_dir, "packages_cran.txt"), packages_cran)
        with open(os.path.join(ch_dir, "Dockerfile"), "w") as f:
            f.write(chapter_dockerfile(chapter, len(footprint_installable), len(packages_cran)))

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
            "footprint_n": len(footprint_installable),
            "packages_cran_n": len(packages_cran),
        })

    # --- images.yaml: the ONE index for the 2.7 family, in Phase 4 catalog
    # schema so the Phase 4 planner consumes it directly (no bespoke manifest,
    # no second store). Every image appears exactly once. The chapter<->image
    # linkage needs no dedicated field: `name` is the lowercased image and the
    # basename of `dir` is the original-case chapter (e.g.
    # name: epirhandbook-transition_to_r / dir: .../chapters/transition_to_R).
    # GENERATED -- hand-edit footprints.tsv or generate.py, never this file.
    catalog_path = os.path.join(HERE, "images.yaml")
    with open(catalog_path, "w") as f:
        f.write("# GENERATED by generate.py -- do not hand-edit; rerun generate.py.\n")
        f.write(f"# The {IMAGE_TAG} per-chapter split catalog (Phase 4 schema). Per chapter row:\n")
        f.write("#   renders -- the .qmd rendered AT RUNTIME (mounted at docker run; it\n")
        f.write("#              is never COPYed into the image)\n")
        f.write("#   dir     -- this image's own files: change-detection scope, and where\n")
        f.write("#              its Dockerfile lives\n")
        f.write("#   context -- the docker build context, i.e. the root COPY resolves\n")
        f.write(f"#              against (epirhandbook/{IMAGE_TAG}, NOT the chapter dir -- building\n")
        f.write("#              with the chapter dir as context fails: pak_install_subset.R\n")
        f.write("#              (and, for common, packages_github.json) are outside it)\n")
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
    print(f"chapters in verify_render_26.04.tsv rc=0 (target set): {len(target_chapters)}")
    print(f"  of those, WITH a footprint row (delta image): {len(target_chapters) - len(no_footprint)}")
    print(f"  of those, NO footprint row (bare common image): {len(no_footprint)}"
          + (f" -> {', '.join(no_footprint)}" if no_footprint else ""))
    print(f"COMMON_THRESHOLD: {COMMON_THRESHOLD}")
    print(f"common: raw names >= threshold (incl. base-R) = {len(common_raw)}")
    print(f"common: installable (minus BASE_R_PACKAGES)    = {len(common_installable)}")
    print(f"common: packages_cran.txt (minus GitHub names too) = {len(common_cran)}")
    print(f"GitHub-pinned names (excluded everywhere, installed via packages_github.json): "
          f"{len(github_names)} -> {', '.join(sorted(github_names))}")
    print("CRAN/Bioc snapshot: owned by rbase's Rprofile.site (single source of truth for versions)")
    print()
    print("chapter\traw_footprint\tfootprint(installable)\tpackages_cran")
    for s in summary:
        print(f"{s['chapter']}\t{s['raw_footprint_n']}\t{s['footprint_n']}\t{s['packages_cran_n']}")
    print()
    print(f"-> {freq_path}")
    print(f"-> {catalog_path}")
    print(f"-> {os.path.join(common_dir, 'packages_cran.txt')}")
    print(f"-> {os.path.join(common_dir, 'Dockerfile')}")
    print(f"-> chapters/<chapter>/ for {len(target_chapters)} chapters "
          f"({len(target_chapters) - len(no_footprint)} with footprint.txt+packages_cran.txt+Dockerfile, "
          f"{len(no_footprint)} bare Dockerfile only)")


if __name__ == "__main__":
    main()
