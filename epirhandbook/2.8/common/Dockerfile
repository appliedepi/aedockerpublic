# syntax=docker/dockerfile:1
# epirhandbook-common:2.8 -- shared base for the group-image split, on the
# 2026 package stack. Same shape as epirhandbook/2.7/common/Dockerfile
# (Phase 5b's per-chapter common image); hand-edit this file directly, the
# way 2.7's own common/Dockerfile is hand-edited (not generated).
#
# The common set: common/packages_cran.txt (56 names) is copied unchanged
# from epirhandbook/2.7/common/packages_cran.txt -- see that file's own
# header for how the 56 were chosen. NO closure: pak resolves the hard
# dependencies itself (dependencies = NA -- not Suggests) against the
# immutable dated snapshot below.
#
# BASE_IMAGE mirrors epirhandbook/2.6 and 2.7's own ARG pattern: a floating
# local tag by default, overridden at build time to a digest pin that
# build_image.sh resolves LIVE from the registry (see that script's
# base-resolution block).
ARG BASE_IMAGE=rbase:4.6.0-2026-07-01
FROM ${BASE_IMAGE}

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
# contradict it. If a newer package is ever needed, move rbase's snapshot
# date -- never assert a version.
RUN R -e "install.packages(c('pak', 'jsonlite', 'BiocManager')); stopifnot(requireNamespace('pak', quietly = TRUE), requireNamespace('jsonlite', quietly = TRUE), requireNamespace('BiocManager', quietly = TRUE))"

COPY packages_github.json packages_github.json
COPY pak_install_subset.R pak_install_subset.R
COPY common/packages_cran.txt packages_cran.txt

# --- Install the common set's 56 CRAN/Bioc names + all 9 GitHub pins,
# --- then let pak resolve hard dependencies (dependencies = NA -- Depends/Imports/LinkingTo, not Suggests) against the
# --- immutable dated snapshot -- NO pre-computed closure --------------------
# GITHUB_PAT is a BuildKit SECRET (never ARG+ENV -- an ENV bakes the token
# into the image's Config.Env, where `docker inspect` leaks it). common is the
# ONE image that installs all 9 GitHub pins (via packages_github.json): every
# group image is FROM common, so every group inherits them, and a
# transitive pull anywhere downstream resolves to the pinned commit rather
# than re-resolving the package from CRAN.
#
# appliedepidata (appliedepi/appliedepidata) is the 9th pin, added for 2.8: a
# GitHub-only package with no CRAN release, so it belongs here rather than in
# any group's packages_cran.txt. Its own dependencies (cli, clipr, dplyr,
# reactable, rio, rstudioapi, shiny, tidyr) are not listed anywhere by name --
# pak resolves them itself (dependencies = NA), exactly like every other
# GitHub pin above.
RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" \
    Rscript pak_install_subset.R packages_cran.txt packages_github.json \
    && rm -rf /tmp/*

# --- The render entrypoint every group image inherits (FROM common) --------
# common/build_one_chapter.sh ALREADY EXISTS -- not generated here, just
# installed onto PATH so every group image can call it by name.
COPY common/build_one_chapter.sh /usr/local/bin/build_one_chapter.sh
RUN chmod +x /usr/local/bin/build_one_chapter.sh

# --- Book-level render tooling: also installed onto PATH, also inherited by
# --- every group image, but only ever RUN against the common image itself
# --- (see build_all_chapters.sh's COMMON_IMAGE) -- these are per-BOOK steps
# --- (per-language config rewrite, the language-switcher post-pass, and the
# --- orchestrator script that drives both), not per-group ones, so which
# --- group image happens to also carry them is irrelevant. Stored here
# --- once so every image has the same single source of truth. -------------
COPY common/rewrite_lang_config.R /usr/local/bin/rewrite_lang_config.R
COPY common/inject_language_links.R /usr/local/bin/inject_language_links.R
COPY common/inject_language_links.sh /usr/local/bin/inject_language_links.sh
COPY common/build_all_chapters.sh /usr/local/bin/build_all_chapters.sh
RUN chmod +x /usr/local/bin/rewrite_lang_config.R \
             /usr/local/bin/inject_language_links.R \
             /usr/local/bin/inject_language_links.sh \
             /usr/local/bin/build_all_chapters.sh

# --- Build-time invariant: every package in packages_cran.txt LOADS, AND
# --- appliedepidata (the GitHub-only 9th pin, not in packages_cran.txt
# --- because it has no CRAN release) LOADS too -- extending the existing
# --- check rather than adding a second one, so there is still exactly one
# --- place a missing/broken package fails the build. ------------------------
RUN R -e "targets <- readLines('packages_cran.txt'); targets <- targets[nzchar(targets)]; targets <- c(targets, 'appliedepidata'); bad <- targets[!vapply(targets, requireNamespace, logical(1), quietly = TRUE)]; if (length(bad)) { message('LOAD CHECK FAILED (', length(bad), '): ', paste(bad, collapse = ', ')); quit(status = 1L) }; message('LOAD CHECK OK: all ', length(targets), ' target packages load')"
