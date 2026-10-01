# syntax=docker/dockerfile:1
# epirhandbook-common:2.9 -- shared base for the group-image split, on the
# 2026 package stack. Same shape as 2.7's own common/Dockerfile, in git history,
# (Phase 5b's per-chapter common image); hand-edit this file directly, the
# way 2.7's own common/Dockerfile is hand-edited (not generated).
#
# The common set: common/packages_cran.txt (58 names) is the 56 packages most
# chapters share (chosen in 2.7 from the per-chapter footprints: the names
# present in most of them), plus fs and xml2. inject_language_links.R
# loads fs and xml2 directly, and nothing else in this image guarantees
# them. brio was here too, for the config rewriter that 2.9 deleted. It was
# kept through the 2.9 rewrite to hold the package set steady, then removed
# once that rewrite had landed. NO closure: pak resolves the hard
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

# --- Install the common set's 59 CRAN/Bioc names + all 7 GitHub pins,
# --- then let pak resolve hard dependencies (dependencies = NA -- Depends/Imports/LinkingTo, not Suggests) against the
# --- immutable dated snapshot -- NO pre-computed closure --------------------
# GITHUB_PAT is a BuildKit SECRET (never ARG+ENV -- an ENV bakes the token
# into the image's Config.Env, where `docker inspect` leaks it). common is the
# ONE image that installs all 7 GitHub pins (via packages_github.json): every
# group image is FROM common, so every group inherits them, and a
# transitive pull anywhere downstream resolves to the pinned commit rather
# than re-resolving the package from CRAN.
#
# Two pins are GitHub-only packages, so they belong here rather than in any
# group's packages_cran.txt. appliedepidata (added for 2.8) has no CRAN
# release. i2extras (reconverse/i2extras) is not on the dated PPM snapshot.
# Their own dependencies are not listed anywhere by name. pak resolves them
# itself (dependencies = NA), as it does for every other GitHub pin. For
# i2extras that means incidence2 (Depends) and ciTools (Imports).
RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" \
    Rscript pak_install_subset.R packages_cran.txt packages_github.json \
    && rm -rf /tmp/*

# --- The render entrypoint every group image inherits (FROM common) --------
# common/build_one_chapter.sh ALREADY EXISTS -- not generated here, just
# installed onto PATH so every group image can call it by name.
COPY common/build_one_chapter.sh /usr/local/bin/build_one_chapter.sh
RUN chmod +x /usr/local/bin/build_one_chapter.sh

# --- The R profile of every chapter render. build_all_chapters.sh passes
# --- -e R_PROFILE_USER=/usr/local/lib/ehb/warnings_to_log.R, so this path
# --- and that script's R_PROFILE_IN_IMAGE MUST stay the same. It logs
# --- every chunk warning as an EHB-WARNING line; see its header. ----------
COPY common/warnings_to_log.R /usr/local/lib/ehb/warnings_to_log.R

# --- The smoke document. build_image.sh renders it in this image, and in
# --- each image built FROM it, before it pushes the image. That script reads
# --- it from this path, so the two MUST stay the same. ---------------------
COPY common/smoke.qmd /usr/local/lib/ehb/smoke.qmd

# --- Book-level render tooling: also installed onto PATH, also inherited by
# --- every group image, but only ever RUN against the common image itself
# --- (see build_all_chapters.sh's COMMON_IMAGE) -- these are per-BOOK steps
# --- (the language-switcher post-pass, and the orchestrator script that
# --- drives it), not per-group ones, so which group image happens to also
# --- carry them is irrelevant. Stored here once so every image has the
# --- same single source of truth. ----------------------------------------
COPY common/inject_language_links.R /usr/local/bin/inject_language_links.R
COPY common/inject_language_links.sh /usr/local/bin/inject_language_links.sh
COPY common/build_all_chapters.sh /usr/local/bin/build_all_chapters.sh
RUN chmod +x /usr/local/bin/inject_language_links.R \
             /usr/local/bin/inject_language_links.sh \
             /usr/local/bin/build_all_chapters.sh

# --- Build-time invariant, in one place. Every package in packages_cran.txt
# --- LOADS. Every GitHub pin LOADS, and its installed RemoteSha equals the
# --- RemoteSha in packages_github.json. The pin names come from that file,
# --- never from a list here, so a new pin is checked without an edit. -------
RUN R -e "targets <- readLines('packages_cran.txt'); targets <- targets[nzchar(targets)]; \
    pins <- jsonlite::fromJSON('packages_github.json')[['GitHubPins']]; \
    targets <- c(targets, names(pins)); \
    bad <- targets[!vapply(targets, requireNamespace, logical(1), quietly = TRUE)]; \
    if (length(bad)) { message('LOAD CHECK FAILED (', length(bad), '): ', paste(bad, collapse = ', ')); quit(status = 1L) }; \
    message('LOAD CHECK OK: all ', length(targets), ' target packages load'); \
    want <- vapply(pins, function(x) x[['RemoteSha']], character(1)); \
    got <- vapply(names(pins), function(p) { s <- packageDescription(p)[['RemoteSha']]; if (is.null(s)) NA_character_ else s }, character(1)); \
    off <- names(pins)[is.na(got) | got != want]; \
    if (length(off)) { message('PIN CHECK FAILED (', length(off), '): ', paste0(off, ' installed at ', got[off], ', pinned at ', want[off], collapse = '; ')); quit(status = 1L) }; \
    message('PIN CHECK OK: all ', length(pins), ' GitHub pins load at their pinned RemoteSha: ', paste(names(pins), collapse = ', '))"
