# syntax=docker/dockerfile:1
# epirhandbook-common:2.9: the shared base for the group images, on the 2026
# package stack. It has the same shape as the common/Dockerfile of 2.7 (the
# per-chapter common image of Phase 5b), which is in git history. No script
# generates this file. Edit it by hand, as 2.7 did.
#
# The common set: common/packages_cran.txt (58 names) holds 56 packages that
# most chapters share, plus fs and xml2. The 56 were chosen in 2.7 from the
# per-chapter footprints, as the names present in most of them.
# inject_language_links.R loads fs and xml2 directly, and nothing else in
# this image makes sure that they are present. brio was here for the config
# rewriter that 2.9 deleted. It stayed during the 2.9 rewrite to keep the
# package set stable, and was removed after the rewrite was merged. There is
# NO closure: pak resolves the hard dependencies itself (dependencies = NA,
# not Suggests) against the dated snapshot below, which does not change.
#
# BASE_IMAGE uses the same ARG pattern as epirhandbook/2.6 and 2.7. The
# default is a floating local tag. At build time, build_image.sh replaces it
# with a digest pin that it resolves LIVE from the registry. See the
# base-resolution block of that script.
ARG BASE_IMAGE=rbase:4.6.0-2026-07-01
FROM ${BASE_IMAGE}

WORKDIR /home/handbook

# --- pak + jsonlite + BiocManager bootstrap ---------------------------------
# rbase:4.6.0 has no R packages. pak is the installer. This Dockerfile AND
# pak_install_subset.R need jsonlite to parse JSON. BiocManager gives
# BiocManager::version(), the Bioconductor release paired with R. It comes
# from the R version, so no second file stores it.
# There is NO repos= and NO minimum version. The Rprofile.site of rbase
# already sets the dated PPM snapshot as the default repo. THAT date is the
# one source of every version, and install.packages() inherits it. A pak
# version stated here would be a second source. It could only agree with the
# date or contradict it. If you need a newer package, move the snapshot date
# of rbase. Do not state a version.
RUN R -e "install.packages(c('pak', 'jsonlite', 'BiocManager')); stopifnot(requireNamespace('pak', quietly = TRUE), requireNamespace('jsonlite', quietly = TRUE), requireNamespace('BiocManager', quietly = TRUE))"

COPY packages_github.json packages_github.json
COPY pak_install_subset.R pak_install_subset.R
COPY common/packages_cran.txt packages_cran.txt

# --- Install the 58 CRAN/Bioc names of the common set and all 7 GitHub pins.
# --- pak then resolves the hard dependencies (dependencies = NA: Depends,
# --- Imports and LinkingTo, not Suggests) against the dated snapshot, which
# --- does not change. There is NO closure computed in advance. -------------
# GITHUB_PAT is a BuildKit SECRET. Do not use ARG+ENV: an ENV writes the token
# into Config.Env of the image, where `docker inspect` shows it. common is the
# ONE image that installs all 7 GitHub pins, from packages_github.json. Every
# group image is FROM common, so every group inherits them. A transitive
# dependency in any later image then uses the pinned commit, and pak does
# not resolve that package from CRAN again.
#
# Two pins are packages that exist only on GitHub, so they are here and not
# in the packages_cran.txt of a group. appliedepidata (added for 2.8) has no
# CRAN release. i2extras (reconverse/i2extras) is not on the dated PPM
# snapshot. No file lists their dependencies by name. pak resolves them
# (dependencies = NA), as it does for every other GitHub pin. For i2extras,
# these are incidence2 (Depends) and ciTools (Imports).
RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" \
    Rscript pak_install_subset.R packages_cran.txt packages_github.json \
    && rm -rf /tmp/*

# --- The render entrypoint that every group image inherits (FROM common) ---
# common/build_one_chapter.sh is a file in this repository. This step puts it
# on PATH, so every group image can call it by name.
COPY common/build_one_chapter.sh /usr/local/bin/build_one_chapter.sh
RUN chmod +x /usr/local/bin/build_one_chapter.sh

# --- The R profile of every chapter render. build_all_chapters.sh passes
# --- -e R_PROFILE_USER=/usr/local/lib/ehb/warnings_to_log.R, so this path
# --- and R_PROFILE_IN_IMAGE in that script MUST stay the same. The profile
# --- logs every chunk warning as an EHB-WARNING line. See its header. -----
COPY common/warnings_to_log.R /usr/local/lib/ehb/warnings_to_log.R

# --- The smoke document. build_image.sh renders it in this image, and in
# --- each image built FROM it, before it pushes the image. That script reads
# --- it from this path, so the two paths MUST stay the same. ---------------
COPY common/smoke.qmd /usr/local/lib/ehb/smoke.qmd

# --- Render tools for the whole book. They are on PATH, and every group
# --- image inherits them. They RUN only against the common image itself
# --- (see COMMON_IMAGE in build_all_chapters.sh). They are steps for the
# --- whole BOOK: the language-switcher pass, and the script that runs it.
# --- It does not matter which group images also hold them. They are stored
# --- here once, so every image has the same copy. --------------------------
COPY common/inject_language_links.R /usr/local/bin/inject_language_links.R
COPY common/inject_language_links.sh /usr/local/bin/inject_language_links.sh
COPY common/build_all_chapters.sh /usr/local/bin/build_all_chapters.sh
RUN chmod +x /usr/local/bin/inject_language_links.R \
             /usr/local/bin/inject_language_links.sh \
             /usr/local/bin/build_all_chapters.sh

# --- Build-time check, in one place. Every package in packages_cran.txt
# --- LOADS. Every GitHub pin LOADS, and its installed RemoteSha equals the
# --- RemoteSha in packages_github.json. The pin names come from that file,
# --- not from a list here, so a new pin is checked with no edit here. ------
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
