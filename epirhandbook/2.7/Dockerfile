# syntax=docker/dockerfile:1
# epirhandbook:2.7-discovery — Phase 5b step 1 (modern base + breakage discovery)
#
# A THROWAWAY image, not a product. Its only job is to answer one question:
# when the FROZEN Sep-18-2024 handbook content is rendered against 2026
# packages, what actually breaks? The real 2.7 images are built later, after
# the forward-port, from a Dockerfile informed by what this one finds.
#
# It installs the same 473 package NAMES as epirhandbook/2.5's renv.lock, at
# whatever versions rbase:4.6.0's pinned CRAN snapshot serves — a RE-RESOLVE,
# not a restore. See pak_reresolve.R for why every ref here is a bare name
# while epirhandbook/2.5/pak_install.R pins every single one.
#
# WHY IT DELIBERATELY HAS NO "all 473 installed" ASSERTION, unlike 2.5:
# some 2024 names are archived off CRAN by 2026, and enumerating them is a
# deliverable of this step. An image that refused to build on the first
# archived package would produce no inventory at all. pak_reresolve.R records
# every failure with its reason into /home/handbook/pkg_status.tsv and exits 0.
# That file, not the build's exit code, is the result.
ARG BASE_IMAGE=rbase:4.6.0
FROM ${BASE_IMAGE}

WORKDIR /home/handbook

# --- pak + jsonlite bootstrap -----------------------------------------------
# Both are BUILD tools, not part of the answer: pak drives the install, and
# jsonlite reads renv.lock for its package NAMES. They come from the base
# image's pinned snapshot like everything else, so nothing here reaches a
# floating repo. jsonlite is bootstrapped explicitly because pak vendors its
# own copy privately, not loadable as jsonlite::.
RUN R -e "install.packages(c('pak', 'jsonlite')); stopifnot(requireNamespace('pak', quietly = TRUE), requireNamespace('jsonlite', quietly = TRUE)); cat('pak', as.character(packageVersion('pak')), '| jsonlite', as.character(packageVersion('jsonlite')), '\n')"

# renv.lock is byte-identical to epirhandbook/2.5/renv.lock. It is carried here
# ONLY as the list of 473 names (and as the 2024 versions to report the 2026
# resolution against). No version in it is installed.
COPY renv.lock renv.lock
COPY pak_reresolve.R pak_reresolve.R

# --- Re-resolve the 473 names against the pinned snapshot -------------------
# GITHUB_PAT (needed to resolve the 7 GitHub-sourced packages without hitting
# the unauthenticated GitHub API rate limit) is a BuildKit SECRET, mounted only
# for this RUN. It is deliberately NOT ARG+ENV: an ENV bakes the token into the
# image Config.Env, where docker inspect leaks it. A secret mount never touches
# any layer or the build history.
# --mount=type=cache persists pak's download/build cache across separate
# `docker build` runs.
# The trailing `rm -rf /tmp/*` runs in THIS layer so pak's build scratch (~4 GB
# of unpacked sources and object files) is not committed into the image; leaving
# it in doubled the equivalent 2.5 image.
RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" Rscript pak_reresolve.R \
    && rm -rf /tmp/*

# --- Report, do not assert ---------------------------------------------------
# Prints the ledger into the build log so the counts are visible without
# running the image. Exits 0 whatever it finds, for the reason in the header.
RUN R -e "d <- read.delim('/home/handbook/pkg_status.tsv', stringsAsFactors = FALSE); ok <- d[['installed']] == 'yes' & d[['loads']] == 'yes'; cat('RE-RESOLVE:', sum(ok), 'of', nrow(d), 'names installed and loading;', sum(!ok), 'failed\n'); if (any(!ok)) write.table(d[!ok, c('name','version_2024','version_2026','reason')], sep = ' | ', quote = FALSE, row.names = FALSE)"
