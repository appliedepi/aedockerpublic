# syntax=docker/dockerfile:1
# rbase:4.6.0 — Applied Epi own R base image (R 4.6.0, Ubuntu 26.04 LTS "Resolute Raccoon")
#
# The MODERN base for Phase 5b. Same self-owned pattern as rbase/4.3.2:
# `FROM ubuntu:<lts>` + R installed from Posit's public r-builds .deb, with NO
# dependency on the rocker project. It installs NO R packages — each product
# image layers its own set on top.
#
# WHAT CHANGES vs rbase/4.3.2:
#   R 4.3.2 -> 4.6.0, Quarto 1.4.550 -> 1.9.38, Ubuntu 22.04 (jammy) -> 26.04
#   (resolute), and a PINNED Posit Package Manager snapshot as the CRAN repo
#   (rbase/4.3.2 left the CRAN repo at R's default and let epirhandbook/2.5
#   point pak at cloud.r-project.org per-package from renv.lock).
#
# WHY THE OS MOVES TO 26.04, after a first attempt held it at 22.04.
# This image was FIRST built `FROM ubuntu:jammy`, at rbase/4.3.2's exact
# digest, to keep the OS out of the experiment: change the packages, hold
# everything else. That reasoning was wrong, and the build disproved it.
# Jammy ships GDAL 3.4.1 (2022). The 2026 geospatial packages are written
# against a newer GDAL C++ API, so `terra` 1.9-34 does not compile on it:
#
#   configure: GDAL: 3.4.1
#   gdal_multidimensional.cpp:1090:49: error: no matching function for call to
#     'GDALMDArray::AsClassicDataset(...)'   candidate expects 2 arguments, 3 provided
#   ERROR: compilation failed for package 'terra'
#
# Five packages failed for that one reason — terra, tmap, raster, leafem,
# OpenStreetMap. None is archived from CRAN; the base was simply too old to
# build them. A "2026 packages" image that cannot install the 2026 geospatial
# stack does not answer the question Phase 5b asks, so the OS moves forward to
# an LTS contemporary with the packages. Ubuntu 26.04 ships GDAL 3.12.2 and
# GEOS 3.14.1.
#
# WHY 26.04 rather than 24.04, which also works. Both install all 473 names
# identically (468 load; the 5 that do not are archived off CRAN, not a base
# problem), so this is a LONGEVITY choice, not a correctness one. 24.04 shipped
# April 2024 and pairing it with a 2026 package set repeats, in miniature, the
# same mistake that broke terra: an OS meaningfully older than the packages it
# must build. 26.04 is the LTS contemporary with this snapshot, which pushes
# the next "system library too old" wall out by roughly two more years.
#
# The build-time GDAL assert below exists so this specific regression cannot
# silently return: a base whose GDAL is older than 3.6 fails the build.
#
# Everything else about the image's shape is unchanged from rbase/4.3.2: the
# sysdep list (two package RENAMES aside, noted at that layer), the compiler
# toolchain, the JDK, `R CMD javareconf`, the openblas-pthread BLAS/LAPACK
# alternative, and the optional SSH runtime toggle.
#
# Ubuntu pinned by DIGEST (immutable) for reproducibility.
FROM ubuntu:26.04@sha256:7c2884fd32770fc6c173b78e0dc2278a2851d89f5447919edbc45475ac55dd6a

ARG R_VERSION=4.6.0
ENV R_VERSION=${R_VERSION}
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# --- The pinned CRAN snapshot ------------------------------------------------
# Phase 5b's SINGLE SOURCE OF TRUTH for package versions, exactly as
# epirhandbook/2.5's renv.lock is for the frozen stack. A dated Posit Package
# Manager snapshot is immutable: the same URL serves the same package versions
# forever, so "which versions did this image get" is answerable from the
# Dockerfile alone, with no lockfile to carry.
#
# WHY 2026-07-01 specifically: a calendar-date snapshot (not an opaque
# transaction id, so a human can read what it means), taken on a month
# boundary, and comfortably materialised — PPM's own service build at the time
# of writing is 2026.06.0, built 2026-06-30. It is ~3 weeks before this image
# was first built, which is recent enough to be a genuine "2026 packages"
# answer while old enough that the snapshot is settled.
#
# WHY the __linux__/resolute path (binaries), not the source path: the snapshot's
# resolute binaries were compiled against 26.04's OWN system libraries, so they
# link against exactly the GDAL/GEOS/PROJ this image installs. It is also
# roughly an order of magnitude faster than compiling ~500 packages from
# source. Packages with no resolute binary fall back to source from this same
# snapshot automatically.
#
# The distribution in this path MUST match the FROM above. A 26.04 image
# pointed at the jammy binary path would install binaries linked against
# libraries it does not have.
#
# NEVER `latest`. A floating snapshot would silently re-resolve every rebuild,
# which is the exact failure Phase 5b exists to characterise. The build-time
# assert below rejects a URL that does not end in a literal YYYY-MM-DD.
#
# The snapshot DATE is the single source of truth for every package version,
# and it is NOT typed here as a literal -- it is DERIVED FROM THIS IMAGE'S TAG.
# build_image.sh reads the YYYY-MM-DD suffix of the tag
# (rbase:4.6.0-2026-07-01) and passes it as --build-arg CRAN_SNAPSHOT_DATE; the
# URL is built from it, so the date lives in exactly one place -- the tag.
# There is deliberately NO default: a bare `docker build` for local testing
# must pass --build-arg CRAN_SNAPSHOT_DATE=YYYY-MM-DD, and a forgotten one
# yields a URL ending in "resolute/", which the YYYY-MM-DD assert below
# rejects loudly rather than silently pinning a stale date.
ARG CRAN_SNAPSHOT_DATE
ARG CRAN_SNAPSHOT=https://packagemanager.posit.co/cran/__linux__/resolute/${CRAN_SNAPSHOT_DATE}

# apt: resilient to transient network blips
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries

# --- Locale (handbook content is UTF-8) -------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends locales \
    && locale-gen en_US.UTF-8 && rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANGUAGE=en_US:en

# --- System dependencies ----------------------------------------------------
# rbase/4.3.2's list, with TWO package renames forced by Ubuntu >= 24.04 and
# nothing else changed: Phase 5b changes the package versions, not the OS
# surface. The handbook's own CI apt list (render_book_on_pr.yml:42), MINUS the
# two ubuntu R packages `r-base-dev` and `r-cran-rjava` (on bare ubuntu those
# pull ubuntu's own R, which would collide with the Posit R below).
# openjdk-11-jdk stays for rJava via `R CMD javareconf`;
# build-essential/gfortran/cmake are the toolchain bare ubuntu lacks;
# libopenblas0-pthread is the SAME BLAS/LAPACK rbase/4.3.2 uses, so a numeric
# difference between the two images cannot be blamed on the BLAS. libgsl-dev is
# for SemiCompRisks.
#
# THE TWO RENAMES, both because 24.04 dropped the 22.04 spelling:
#   libfreetype6-dev -> libfreetype-dev  (24.04 keeps the old name only as a
#                       virtual `Provides:`; naming the real package avoids
#                       depending on apt's single-provider resolution.)
#   libv8-dev        -> dropped          (22.04 shipped it as a transitional
#                       package that just pulled libnode-dev. 24.04 removed it
#                       and libnode-dev — already in this list — carries
#                       `Provides: libv8-dev`, so the V8 headers the R package
#                       V8 needs are still installed.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl gnupg \
    build-essential gfortran cmake pkg-config \
    zlib1g-dev libbz2-dev liblzma-dev libpcre2-dev libicu-dev \
    libopenblas0-pthread \
    openjdk-11-jdk \
    libcurl4-openssl-dev libxml2-dev libssl-dev libfontconfig1-dev libharfbuzz-dev libfribidi-dev libfreetype-dev libpng-dev libtiff5-dev libjpeg-dev libglpk-dev gdal-bin libgdal-dev libxslt1-dev libgit2-dev libgeos-dev libproj-dev libudunits2-dev libcairo2-dev libxt-dev libmagick++-dev libpoppler-cpp-dev libpq-dev libmysqlclient-dev libsqlite3-dev libssh2-1-dev libgmp3-dev libmpfr-dev libprotobuf-dev protobuf-compiler libgl1-mesa-dev libglu1-mesa-dev libpoppler-glib-dev libtbb-dev libsodium-dev libnetcdf-dev netcdf-bin libjq-dev libnode-dev jq \
    libgsl-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Build-time invariant: the geospatial C libraries are new enough --------
# THE reason this image is not on Ubuntu 22.04. Ubuntu 22.04's
# GDAL 3.4.1 cannot compile terra 1.9-34 (and so not tmap, raster, leafem or
# OpenStreetMap either): the package calls the 3-argument
# GDALMDArray::AsClassicDataset(), which 3.4 does not have. GDAL 3.6 is the
# first release with that signature, so 3.6 is the floor.
#
# This assert makes the regression impossible to reintroduce quietly. Rebase
# this image on an older distribution and the build stops HERE, with the
# version printed, instead of 40 minutes later inside a C++ compile log.
#
# `sort -V -C` succeeds only when its input is already in version order, so
# feeding it "3.6" then the detected version is exactly the test
# `3.6 <= detected`.
RUN gdal_ver="$(gdal-config --version)" \
    && geos_ver="$(geos-config --version)" \
    && proj_ver="$(pkg-config --modversion proj)" \
    && echo "GDAL ${gdal_ver} | GEOS ${geos_ver} | PROJ ${proj_ver}" \
    && { printf '%s\n%s\n' 3.6 "${gdal_ver}" | sort -V -C \
         || { echo "FATAL: GDAL ${gdal_ver} is older than the required 3.6" >&2; exit 1; }; }

# Force the BLAS/LAPACK alternatives to openblas-pthread (same as rbase/4.3.2).
RUN update-alternatives --set "libblas.so.3-$(uname -m)-linux-gnu" "/usr/lib/$(uname -m)-linux-gnu/openblas-pthread/libblas.so.3" \
    && update-alternatives --set "liblapack.so.3-$(uname -m)-linux-gnu" "/usr/lib/$(uname -m)-linux-gnu/openblas-pthread/liblapack.so.3"

# --- R 4.6.0 from Posit r-builds (NOT rocker) -------------------------------
# Posit's prebuilt R .deb installs into /opt/R/${R_VERSION}; `apt-get install -f`
# resolves R's runtime deps. The sha256 is checked BEFORE the .deb is installed,
# so a substituted or truncated download fails the build rather than producing a
# silently different R. Symlink R/Rscript onto PATH, then javareconf wires R to
# the JDK for rJava.
#
# The `ubuntu-2604` path segment tracks the FROM above: Posit builds one .deb
# per Ubuntu release, and the 22.04 and 24.04 builds of the same R version are
# different binaries with different checksums.
RUN wget --tries=5 --retry-connrefused --waitretry=10 -q \
      -O /tmp/R.deb "https://cdn.rstudio.com/r/ubuntu-2604/pkgs/r-${R_VERSION}_1_amd64.deb" \
    && echo "6607ccb82db48bae27e9012bf38887bec64df07206c842311260a692c48233dd  /tmp/R.deb" | sha256sum -c - \
    && apt-get update \
    && apt-get install -f -y --no-install-recommends /tmp/R.deb \
    && ln -s /opt/R/${R_VERSION}/bin/R /usr/local/bin/R \
    && ln -s /opt/R/${R_VERSION}/bin/Rscript /usr/local/bin/Rscript \
    && rm /tmp/R.deb && rm -rf /var/lib/apt/lists/*
RUN R CMD javareconf

# --- Rprofile.site: the pinned snapshot IS the CRAN repo --------------------
# Written into R's own site profile so EVERY R process in every image built on
# top of this one gets the same repo with no further configuration, and so a
# product image cannot forget to set it.
#
# HTTPUserAgent is load-bearing, not decoration: PPM decides whether to serve a
# BINARY or the source tarball from the R version in the request's user agent.
# R's default agent does carry the version, but setting it explicitly (Posit's
# own documented snippet) makes the binary path independent of R's default
# formatting.
RUN printf '%s\n' \
    "options(" \
    "  repos = c(CRAN = \"${CRAN_SNAPSHOT}\")," \
    "  HTTPUserAgent = sprintf(" \
    "    \"R/%s R (%s)\"," \
    "    getRversion()," \
    "    paste(getRversion(), R.version[[\"platform\"]], R.version[[\"arch\"]], R.version[[\"os\"]])" \
    "  )," \
    "  download.file.method = \"libcurl\"" \
    ")" \
    >> /opt/R/${R_VERSION}/lib/R/etc/Rprofile.site

# --- Build-time invariants ---------------------------------------------------
# 1. R is EXACTLY the expected version.
# 2. BLAS/LAPACK is openblas (same alternative as rbase/4.3.2).
# 3. The CRAN repo is EXACTLY the pinned snapshot URL passed in as
#    CRAN_SNAPSHOT — not R's default, not something an earlier layer changed.
# 4. That URL is a DATED snapshot, not a floating one: it must end in a literal
#    YYYY-MM-DD, so `latest` (or any other moving alias) fails the build here
#    rather than silently re-resolving on some future rebuild.
# 5. The repo actually RESOLVES: available.packages() returns a full CRAN-sized
#    index (>= 20000 packages) from it. A typo'd or dead snapshot URL returns an
#    empty index, which this catches.
# The versions of a few well-known packages are printed as the snapshot's
# fingerprint, so the build log records what "2026 packages" concretely meant.
RUN R -e "\
      stopifnot(getRversion() == '${R_VERSION}'); \
      si <- sessionInfo(); \
      cat('R', as.character(getRversion()), '| BLAS', si[['BLAS']], '| LAPACK', si[['LAPACK']], '\n'); \
      stopifnot(grepl('openblas', si[['BLAS']], ignore.case = TRUE), grepl('openblas', si[['LAPACK']], ignore.case = TRUE)); \
      repo <- getOption('repos')[['CRAN']]; \
      cat('CRAN repo:', repo, '\n'); \
      stopifnot(identical(repo, '${CRAN_SNAPSHOT}')); \
      stopifnot(nchar(repo) >= 10L, grepl('^[0-9]{4}-[0-9]{2}-[0-9]{2}', substring(repo, nchar(repo) - 9L))); \
      ap <- available.packages(); \
      cat('available.packages() rows:', nrow(ap), '\n'); \
      stopifnot(nrow(ap) >= 20000); \
      for (p in c('data.table', 'ggplot2', 'dplyr', 'tidyr', 'sf', 'terra')) cat(' snapshot', p, ap[p, 'Version'], '\n')"

# --- Quarto CLI 1.9.38 ------------------------------------------------------
# The current stable Quarto release at the time this image was written (the
# frozen stack's Quarto 1.4.550 is two years old). Pinned to an exact version
# and sha256-verified, never `quarto.org/download/latest`, so a rebuild gets
# the same CLI.
RUN curl -fsSL -o /tmp/quarto.deb https://github.com/quarto-dev/quarto-cli/releases/download/v1.9.38/quarto-1.9.38-linux-amd64.deb \
    && echo "bd0d73c1042fc5f719fb87753f0874c11344e516ee2cfbe4fe3ed4e4458c3988  /tmp/quarto.deb" | sha256sum -c - \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/quarto.deb \
    && rm -rf /tmp/quarto.deb /var/lib/apt/lists/* \
    && quarto --version

# --- Optional SSH runtime toggle (off and keyless by default) ---------------
# Identical to rbase/4.3.2. openssh-server is installed but INERT: sshd does
# not start unless the operator supplies SSH_PUBKEY at `docker run` time (see
# entrypoint.sh) -- there is no separate "enable" flag, so "on with no key" is
# not a state that can be reached. No key of any kind is baked into this image,
# and no password-based login path exists at all.
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/*

COPY sshd_hardening.conf /etc/ssh/sshd_config.d/hardening.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Build-time invariant: the EFFECTIVE sshd config truly disables every
# password-like auth path, root is key-only, AND none of the
# forwarding/tunneling features are reachable either. `sshd -T` needs host keys
# and /run/sshd to exist just to parse/dump config even though it never starts
# the daemon; both are generated/created here ONLY for this check and removed in
# this same layer, so no host key is ever baked into the image --
# entrypoint.sh generates a fresh host key per CONTAINER at start time instead.
RUN ssh-keygen -A \
    && mkdir -p /run/sshd \
    && CFG="$(/usr/sbin/sshd -T)" \
    && echo "$CFG" | grep -qx 'passwordauthentication no' \
    && echo "$CFG" | grep -qx 'kbdinteractiveauthentication no' \
    && echo "$CFG" | grep -qx 'permitemptypasswords no' \
    `# Accept EITHER spelling: they are the same setting, and which one` \
    `# 'sshd -T' prints depends on the OpenSSH version. OpenSSH 9.x (Ubuntu` \
    `# 22.04/24.04) normalizes to the deprecated alias 'without-password';` \
    `# OpenSSH 10.x (Ubuntu 26.04) prints the canonical 'prohibit-password'.` \
    `# Asserting one literal spelling pinned a DISPLAY alias rather than the` \
    `# security property, and broke on a newer OpenSSH. 'yes' still fails.` \
    && echo "$CFG" | grep -qE '^permitrootlogin (without-password|prohibit-password)$' \
    && echo "$CFG" | grep -qx 'allowtcpforwarding no' \
    && echo "$CFG" | grep -qx 'x11forwarding no' \
    && echo "$CFG" | grep -qx 'permittunnel no' \
    && echo "$CFG" | grep -qx 'gatewayports no' \
    && echo "$CFG" | grep -qx 'allowagentforwarding no' \
    && rm -rf /etc/ssh/ssh_host_* /run/sshd

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]
