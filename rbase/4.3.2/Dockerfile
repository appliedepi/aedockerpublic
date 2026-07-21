# syntax=docker/dockerfile:1
# rbase:4.3.2 — Applied Epi own R base image (R 4.3.2, Ubuntu jammy)
# (named rbase, not base, to leave room for a separate pythonbase later)
#
# The shared foundation the epiRhandbook 2.5 image (and future 4.3.2-era
# products) build FROM. It carries the OS toolchain that is stable across
# products: the exact R build, the handbook CI's system libraries, Java, and
# Quarto 1.4.550. It installs NO R packages — each product image layers its own
# package set on top (epirhandbook/2.5 restores the 473 renv.lock packages).
#
# Base choice = MINIMIZED ROCKER, not own-from-ubuntu. Phase 2's regression bar
# is "render byte-for-byte like Phase 1", and Phase 1 was built on
# rocker/r-ver:4.3.2. Keeping that same FROM holds the R build itself identical,
# so the single variable under test in Phase 2 is the installer swap
# (renv -> pak). Rebuilding R from ubuntu would introduce a second, confounding
# variable (different R build flags / BLAS / compiler) that could perturb the
# render and defeat the point of the rehearsal. A greenfield own-from-ubuntu
# base is the sanctioned option for the modern rbase/4.6.0 in Phase 5.
#
# Pinned by DIGEST, not just the :4.3.2 tag: a tag is a movable label the rocker
# project can re-push, so the tag alone would let a rebuild drift onto a newer
# OS layer. The digest is the immutable content hash of the exact image Phase 1
# was built and verified on; a re-pull by tag+digest is byte-identical or fails
# loudly.
FROM rocker/r-ver:4.3.2@sha256:4e32addfc4da3e660f6e0d05ce5e43d3eceb9db58a60b9a142e0dde9a654ead1

# Avoid interactive prompts (tzdata etc.) pulled in transitively by
# openjdk-11-jdk / gdal-bin during apt-get install.
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# --- System dependencies (verbatim apt list from the handbook's own CI) ------
# render_book_on_pr.yml:42. Kept verbatim so this list is auditable against the
# upstream CI. R CMD javareconf wires R to the JDK for rJava.
RUN apt-get update && apt-get install -y \
    libcurl4-openssl-dev libxml2-dev libssl-dev libfontconfig1-dev libharfbuzz-dev libfribidi-dev libfreetype6-dev libpng-dev libtiff5-dev libjpeg-dev libglpk-dev r-cran-rjava r-base-dev openjdk-11-jdk gdal-bin libgdal-dev libxslt1-dev libgit2-dev libgeos-dev libproj-dev libudunits2-dev libcairo2-dev libxt-dev libmagick++-dev libpoppler-cpp-dev libpq-dev libmysqlclient-dev libsqlite3-dev libssh2-1-dev libgmp3-dev libmpfr-dev libprotobuf-dev protobuf-compiler libgl1-mesa-dev libglu1-mesa-dev libpoppler-glib-dev libtbb-dev libsodium-dev libv8-dev libnetcdf-dev netcdf-bin libjq-dev libnode-dev jq \
    && R CMD javareconf \
    && rm -rf /var/lib/apt/lists/*

# --- System deps MISSING from the handbook CI's apt list --------------------
# The CI's render used continue-on-error, so failed compiles didn't block it;
# a strict package restore has no such tolerance. Kept a separate layer so the
# verbatim CI list above stays intact and auditable.
#   - libgsl-dev: SemiCompRisks needs gsl/gsl_matrix.h.
#   - cmake: the pinned nloptr builds its bundled NLopt via CMake.
RUN apt-get update && apt-get install -y libgsl-dev cmake && rm -rf /var/lib/apt/lists/*

# --- Quarto CLI 1.4.550 (the version the handbook CI rendered with) ---------
# Neither curl nor wget exists in rocker/r-ver:4.3.2 and neither is in the CI
# system-deps list above (left untouched), so curl is installed here, scoped to
# this one layer, just to fetch the .deb; the download is checksum-verified.
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL -o /tmp/quarto.deb https://github.com/quarto-dev/quarto-cli/releases/download/v1.4.550/quarto-1.4.550-linux-amd64.deb \
    && echo "5ba82c811f5b12d9e8fa2f45ff306dca2f82472d6944104678c5294a02883164  /tmp/quarto.deb" | sha256sum -c - \
    && apt-get install -y /tmp/quarto.deb \
    && rm -rf /tmp/quarto.deb /var/lib/apt/lists/*

# Phase 4 will add the optional openssh-server (runtime-toggled) here. Left out
# in Phase 2 to keep the base minimal and the render comparison single-variable.
