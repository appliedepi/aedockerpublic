# syntax=docker/dockerfile:1
# epiRhandbook build image — Phase 1 (build-to-green, hardened)
# R 4.3.2 on Ubuntu jammy (base pinned by DIGEST), all 473 renv.lock packages
# restored from source at their exact locked versions (see the MAKEFLAGS comment
# below for why source, not PPM binaries), then a build-time load-check asserts
# every one loads. Rendering the book is a separate, later step.

# Base pinned by digest, not just the :4.3.2 tag: a tag is a movable label the
# rocker project can re-push, so the tag alone would let a rebuild drift onto a
# newer OS layer. The digest is the immutable content hash of the exact image
# this environment was built and verified on. (Digest of rocker/r-ver:4.3.2 as
# pulled 2026-07; re-pull by tag+digest is byte-identical or fails loudly.)
FROM rocker/r-ver:4.3.2@sha256:4e32addfc4da3e660f6e0d05ce5e43d3eceb9db58a60b9a142e0dde9a654ead1

# Avoid interactive prompts (tzdata etc.) pulled in transitively by
# openjdk-11-jdk / gdal-bin during apt-get install.
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# --- System dependencies (verbatim apt list from the handbook's own CI) ---
RUN apt-get update && apt-get install -y \
    libcurl4-openssl-dev libxml2-dev libssl-dev libfontconfig1-dev libharfbuzz-dev libfribidi-dev libfreetype6-dev libpng-dev libtiff5-dev libjpeg-dev libglpk-dev r-cran-rjava r-base-dev openjdk-11-jdk gdal-bin libgdal-dev libxslt1-dev libgit2-dev libgeos-dev libproj-dev libudunits2-dev libcairo2-dev libxt-dev libmagick++-dev libpoppler-cpp-dev libpq-dev libmysqlclient-dev libsqlite3-dev libssh2-1-dev libgmp3-dev libmpfr-dev libprotobuf-dev protobuf-compiler libgl1-mesa-dev libglu1-mesa-dev libpoppler-glib-dev libtbb-dev libsodium-dev libv8-dev libnetcdf-dev netcdf-bin libjq-dev libnode-dev jq \
    && R CMD javareconf \
    && rm -rf /var/lib/apt/lists/*

# --- Quarto CLI 1.4.550 (not used to render in this phase, but the image ---
# --- should be complete for the later render step) -------------------------
# NOTE: neither curl nor wget exists in rocker/r-ver:4.3.2, and they are not
# in the verbatim system-deps list above (that list is left untouched), so
# they're installed here, scoped to this one layer, just to fetch the .deb.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL -o /tmp/quarto.deb https://github.com/quarto-dev/quarto-cli/releases/download/v1.4.550/quarto-1.4.550-linux-amd64.deb \
    && echo "5ba82c811f5b12d9e8fa2f45ff306dca2f82472d6944104678c5294a02883164  /tmp/quarto.deb" | sha256sum -c - \
    && apt-get install -y /tmp/quarto.deb \
    && rm -rf /tmp/quarto.deb /var/lib/apt/lists/*

# --- System deps MISSING from the handbook CI's apt list --------------------
# The CI's apt list omitted these (its render used continue-on-error, so failed
# compiles didn't block it; renv::restore has no such tolerance):
#   - libgsl-dev: SemiCompRisks needs gsl/gsl_matrix.h.
#   - cmake: the pinned nloptr builds its bundled NLopt via CMake.
# Kept as a separate layer so the verbatim CI list above stays intact.
RUN apt-get update && apt-get install -y libgsl-dev cmake && rm -rf /var/lib/apt/lists/*

# --- Pin CRAN to the PPM dated snapshot for the renv BOOTSTRAP install only -
# rocker/r-ver:4.3.2 already points Rprofile.site at PPM
# (https://p3m.dev/cran/__linux__/jammy/<date>) with the HTTPUserAgent PPM
# needs to serve jammy binaries. Only the snapshot DATE is overridden here;
# HTTPUserAgent from the base image's Rprofile.site is untouched.
# NOTE: this option is NOT what governs `renv::restore()` below — renv::restore
# ignores getOption("repos") and uses the lockfile's own R$Repositories field
# instead (unless RENV_CONFIG_REPOS_OVERRIDE is set, which we don't use, since
# a single PPM binary snapshot can't serve every archived version this lockfile
# pins — see the MAKEFLAGS comment below). This line only speeds up the one-off
# `install.packages('renv')` bootstrap a few lines down.
# Bioconductor 3.18 is pinned inside renv.lock itself and renv resolves it
# independently during restore.
RUN echo 'options(repos = c(CRAN = "https://packagemanager.posit.co/cran/__linux__/jammy/2024-03-15"))' >> /usr/local/lib/R/etc/Rprofile.site

# --- Fixed, persistent renv library/cache paths -----------------------------
# A later render stage mounts the actual handbook source over this image; it
# will find the restored library here regardless of where the source lands.
ENV RENV_PATHS_LIBRARY=/opt/renv/library
ENV RENV_PATHS_CACHE=/opt/renv/cache
# RENV_PATHS_CACHE is a BuildKit cache mount (see the restore RUN step below):
# its contents persist ACROSS separate `docker build` runs but are NOT part of
# the final image. renv's default behavior is to install into
# RENV_PATHS_LIBRARY as SYMLINKS into RENV_PATHS_CACHE to save disk — which
# would leave the image's library full of dangling symlinks once the cache
# mount disappears. Force real copies into RENV_PATHS_LIBRARY instead, so the
# committed image layer is self-contained and packages load with no cache
# mount present.
ENV RENV_CONFIG_CACHE_SYMLINKS=FALSE

# The lockfile mixes package versions from different dates: some are current on any
# one PPM binary snapshot, others are archived (source only). renv's PPM binary
# transform breaks its source-archive fallback for the archived ones, so no single
# PPM binary repo can restore the whole lock. Restore from the lockfile's own repo
# (cloud.r-project.org) — which has EVERY version — exactly as the original handbook CI did.
#
# We deliberately do NOT set MAKEFLAGS=-jN. Within-package parallel make breaks any
# package with undeclared Fortran module dependencies — e.g. frailtypack fails with
# "Cannot open module file 'comon.mod'" because a source file that USES a module gets
# compiled before the file that DEFINES it finishes. CRAN/the original CI build serially.
# Cross-package parallelism via options(Ncpus = 12) in the restore step below is race-free
# and gives most of the speedup.

WORKDIR /home/handbook

# --- Vendored lockfile + renv infra (from epiRhandbook_eng committed HEAD) --
COPY renv.lock renv.lock
COPY renv/activate.R renv/activate.R
COPY renv/settings.json renv/settings.json

# --- Fix: reorder R$Repositories so CRAN is probed BEFORE Bioconductor ------
# Root cause of the ~20s-of-silent-work-per-package restore stall: this
# lockfile was snapshotted long ago, so most of its 473 pinned versions are no
# longer CRAN's current release and need renv's CRAN-archive fallback path
# (renv:::renv_retrieve_repos_archive). That path walks every repo in
# R$Repositories IN ORDER and makes a live HTTP probe against each to see
# whether it hosts the package's archive — and this lockfile lists CRAN LAST,
# after the 5 Bioconductor repos. Since a CRAN package is never found on
# Bioconductor, nothing is ever satisfied (or cached) there, so renv burns
# ~1-4.5s probing each of the 5 Bioconductor URLs on EVERY single archived
# package before it ever reaches CRAN — confirmed by timing
# renv:::renv_retrieve_repos_archive_path directly: ~19.5s wasted per package
# with CRAN last vs ~0.1-0.3s with CRAN first (measured against a rocker/
# r-ver:4.3.2 container matching this image, e.g. gargle 1.5.2: 19.5s -> 0.27s;
# a 9-package/30-transitive-dependency restore: crawling at ~20s/pkg -> "30
# packages in 15 seconds" total). This only reorders which repo is checked
# first; it does not change any repository URL or any package's pinned
# version — jq confirms the transformed lockfile is identical to the original
# except for R.Repositories order.
RUN jq '.R.Repositories |= (map(select(.Name=="CRAN")) + map(select(.Name!="CRAN")))' renv.lock > renv.lock.tmp \
    && mv renv.lock.tmp renv.lock

# --- Restore all 473 pinned packages from source, at their exact locked -----
# --- versions ----------------------------------------------------------------
# GITHUB_PAT (needed to resolve the 7 GitHub-SHA-pinned packages — babeldown,
# babelquarto, epicontacts, epidict, epitabulate, sitrep, googlesheets4 —
# without hitting the unauthenticated GitHub API rate limit) is supplied as a
# BuildKit SECRET, mounted only for the restore RUN below. It is deliberately
# NOT `ARG`+`ENV`: an ENV bakes the token into the image's Config.Env, where
# `docker inspect` leaks it to anyone holding the image — unacceptable for a
# public image. A secret mount never touches any layer or the build history.
# renv::restore with a small retry loop: GitHub tarball downloads occasionally
# fail on a transient HTTP/2 stream reset and renv does not retry those. restore
# is incremental (already-installed packages are skipped), so a retry resumes.
# Capped at 2 attempts, not 5: a real compile failure (missing system library,
# bad source) is deterministic and will not be fixed by waiting 20s and
# re-running the same compiler invocation — only transient download blips
# benefit from a retry, and one retry is enough for those.
# --mount=type=cache persists /opt/renv/cache across separate `docker build`
# invocations (BuildKit's build-cache store, independent of layer caching), so
# a later rebuild (e.g. after fixing one missing sysreq) reuses every already-
# compiled package instead of recompiling all 473 from scratch.
RUN --mount=type=cache,target=/opt/renv/cache --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" R -e "install.packages('renv'); stopifnot(packageVersion('renv') == '1.0.5'); options(Ncpus = 12L); \
ok <- FALSE; \
for (i in 1:2) { \
  res <- tryCatch({ renv::restore(prompt = FALSE); TRUE }, error = function(e) { message('restore attempt ', i, ' failed: ', conditionMessage(e)); FALSE }); \
  if (isTRUE(res)) { ok <- TRUE; break }; \
  message('retry in 20s'); Sys.sleep(20) \
}; \
if (!ok) quit(status = 1L)"

# --- Build-time load-check: every locked package must LOAD, not just install -
# Encodes the "all 473 locked packages load" claim as a build-enforced invariant
# instead of an external manual check (codex gate finding). Runs with the renv
# autoloader disabled so R uses the site-library where restore actually installed
# the packages (RENV_PATHS_LIBRARY is a no-op without a project .Rprofile) — the
# same way the later render step loads them. requireNamespace loads each namespace
# and its shared libraries WITHOUT attaching (avoids attach-order masking); any
# package that fails to load fails the build. Uses [[ ]] not $ so no shell/$
# escaping is needed in the RUN string.
RUN RENV_CONFIG_AUTOLOADER_ENABLED=FALSE R -e "lock <- jsonlite::fromJSON('renv.lock', simplifyVector = FALSE); pkgs <- names(lock[['Packages']]); fail <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]; if (length(fail)) { message('LOAD-CHECK FAILED (', length(fail), '): ', paste(fail, collapse = ', ')); quit(status = 1L) }; message('LOAD-CHECK OK: all ', length(pkgs), ' locked packages load')"
