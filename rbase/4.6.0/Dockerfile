# syntax=docker/dockerfile:1
# rbase:4.6.0: the Applied Epi R base image (R 4.6.0, Ubuntu 26.04 LTS
# "Resolute Raccoon")
#
# The MODERN base for Phase 5b. It follows the same self-owned pattern as
# rbase/4.3.2: `FROM ubuntu:<lts>` plus R from Posit's public r-builds .deb,
# with NO dependency on the rocker project. It installs NO R packages. Each
# product image adds its own set on top.
#
# Changes from rbase/4.3.2:
#   - R 4.3.2 -> 4.6.0
#   - Quarto 1.4.550 -> 1.9.38
#   - Ubuntu 22.04 (jammy) -> 26.04 (resolute)
#   - A PINNED Posit Package Manager snapshot as the CRAN repo. rbase/4.3.2
#     left the CRAN repo at R's default, and epirhandbook/2.5 pointed pak at
#     cloud.r-project.org per package from renv.lock.
#
# Why the OS moved to 26.04. The first build of this image was
# `FROM ubuntu:jammy`, at the same digest as rbase/4.3.2. The aim was to
# change the packages and hold everything else. The build showed that this
# does not work. Jammy ships GDAL 3.4.1 (2022). The 2026 geospatial packages
# use a newer GDAL C++ API, so `terra` 1.9-34 does not compile on jammy:
#
#   configure: GDAL: 3.4.1
#   gdal_multidimensional.cpp:1090:49: error: no matching function for call to
#     'GDALMDArray::AsClassicDataset(...)'   candidate expects 2 arguments, 3 provided
#   ERROR: compilation failed for package 'terra'
#
# Five packages failed for that one reason: terra, tmap, raster, leafem and
# OpenStreetMap. CRAN archived none of them. The base was too old to build
# them. Phase 5b asks what a "2026 packages" image looks like, and an image
# without the 2026 geospatial stack cannot answer that. So the OS moved
# forward to an LTS from the same period as the packages. Ubuntu 26.04 ships
# GDAL 3.12.2 and GEOS 3.14.1.
#
# Why 26.04 and not 24.04, which also works. Both install all 473 names in
# the same way (468 load; the 5 that do not are archived off CRAN, not a base
# problem). So the choice is about longevity, not correctness. 24.04 shipped
# in April 2024. With a 2026 package set, it repeats the mistake that broke
# terra on a small scale. The OS is much older than the packages it must
# build. 26.04 is the LTS from the same period as this snapshot. It moves the
# next "system library too old" failure about two years further out.
#
# The build-time GDAL assert below stops this regression from coming back
# unnoticed: the build fails if GDAL is older than 3.6.
#
# The rest of the image is the same as rbase/4.3.2: the sysdep list (except
# two package renames, noted at that layer), the compiler toolchain, the JDK,
# `R CMD javareconf`, the openblas-pthread BLAS/LAPACK alternative, and the
# optional SSH runtime toggle.
#
# Ubuntu pinned by DIGEST (immutable) for reproducibility.
FROM ubuntu:26.04@sha256:7c2884fd32770fc6c173b78e0dc2278a2851d89f5447919edbc45475ac55dd6a

ARG R_VERSION=4.6.0
ENV R_VERSION=${R_VERSION}
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# --- The pinned CRAN snapshot ------------------------------------------------
# The SINGLE SOURCE OF TRUTH for package versions in Phase 5b, as
# epirhandbook/2.5's renv.lock is for the frozen stack. A dated Posit Package
# Manager snapshot is immutable: the same URL serves the same package
# versions forever. So the Dockerfile alone tells you which versions this
# image got, with no lockfile to carry.
#
# Why 2026-07-01:
#   - It is a calendar date, not an opaque transaction id, so a human can
#     read it.
#   - It is on a month boundary.
#   - It is fully materialised. When this was written, PPM's own service
#     build was 2026.06.0, built 2026-06-30.
#   - It is about 3 weeks before the first build of this image. That is
#     recent enough to be a real "2026 packages" answer, and old enough for
#     the snapshot to be settled.
#
# Why the __linux__/resolute path (binaries), not the source path: the
# snapshot's resolute binaries were compiled against the system libraries of
# 26.04. So they link against the GDAL/GEOS/PROJ that this image installs.
# They are also about ten times faster than compiling ~500 packages from
# source. A package with no resolute binary falls back to source from the
# same snapshot automatically.
#
# The distribution in this path MUST match the FROM above. A 26.04 image
# that uses the jammy binary path would install binaries linked against
# libraries it does not have.
#
# NEVER use `latest`. A floating snapshot would re-resolve on every rebuild
# without notice. Phase 5b exists to characterise that failure. The
# build-time assert below rejects a URL that does not end in a literal
# YYYY-MM-DD.
#
# The snapshot DATE is not typed here as a literal. It comes from THIS
# IMAGE'S TAG. build_image.sh reads the YYYY-MM-DD suffix of the tag
# (rbase:4.6.0-2026-07-01) and passes it as --build-arg CRAN_SNAPSHOT_DATE.
# The URL is built from it, so the date exists in one place only: the tag.
# There is NO default. A bare `docker build` for local testing must pass
# --build-arg CRAN_SNAPSHOT_DATE=YYYY-MM-DD. Without it, the URL ends in
# "resolute/", and the YYYY-MM-DD assert below fails the build. A stale
# date cannot be pinned by accident.
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
# The list from rbase/4.3.2, with TWO package renames that Ubuntu >= 24.04
# forces. Nothing else changed: Phase 5b changes the package versions, not
# the OS surface. It is the handbook's own CI apt list (render_book_on_pr.yml:42)
# MINUS the two ubuntu R packages `r-base-dev` and `r-cran-rjava`. On bare
# ubuntu those pull ubuntu's own R, which would collide with the Posit R
# below.
#   - openjdk-11-jdk stays, for rJava via `R CMD javareconf`.
#   - build-essential/gfortran/cmake are the toolchain that bare ubuntu
#     lacks.
#   - libopenblas0-pthread is the SAME BLAS/LAPACK that rbase/4.3.2 uses, so
#     the BLAS cannot cause a numeric difference between the two images.
#   - libgsl-dev is for SemiCompRisks.
#
# THE TWO RENAMES. Both exist because 24.04 dropped the 22.04 spelling:
#   libfreetype6-dev -> libfreetype-dev  (24.04 keeps the old name only as a
#                       virtual `Provides:`. The real package name avoids a
#                       dependency on apt's single-provider resolution.)
#   libv8-dev        -> dropped          (22.04 shipped it as a transitional
#                       package that only pulled libnode-dev. 24.04 removed
#                       it. libnode-dev, already in this list, carries
#                       `Provides: libv8-dev`, so the V8 headers that the R
#                       package V8 needs are still installed.)
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
# This check is THE reason this image is not on Ubuntu 22.04. The GDAL 3.4.1
# in Ubuntu 22.04 cannot compile terra 1.9-34, and so not tmap, raster,
# leafem or OpenStreetMap either. terra calls the 3-argument
# GDALMDArray::AsClassicDataset(), which 3.4 does not have. GDAL 3.6 is the
# first release with that signature, so 3.6 is the floor.
#
# This assert stops the regression from coming back unnoticed. If this image
# moves to an older distribution, the build stops HERE and prints the
# version. Without it, the failure comes 40 minutes later inside a C++
# compile log.
#
# `sort -V -C` succeeds only when its input is already in version order. So
# input of "3.6" and then the detected version tests `3.6 <= detected`.
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
# Posit's prebuilt R .deb installs into /opt/R/${R_VERSION}. `apt-get install
# -f` resolves R's runtime deps. The sha256 is checked BEFORE the .deb is
# installed. So a substituted or truncated download fails the build, and a
# different R cannot be installed without notice. The R/Rscript symlinks go
# onto PATH. Then javareconf connects R to the JDK for rJava.
#
# The `ubuntu-2604` path segment follows the FROM above. Posit builds one
# .deb per Ubuntu release. The 22.04 and 24.04 builds of the same R version
# are different binaries with different checksums.
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
# This goes into R's own site profile. So EVERY R process, in every image
# built on top of this one, gets the same repo with no more configuration.
# A product image cannot forget to set it.
#
# HTTPUserAgent is necessary. PPM uses the R version in the user agent of
# the request to decide whether to serve a BINARY or the source tarball. R's
# default agent does carry the version. Setting it explicitly (Posit's own
# documented snippet) makes the binary path independent of R's default
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
# 1. R is the expected version.
# 2. BLAS/LAPACK is openblas (same alternative as rbase/4.3.2).
# 3. The CRAN repo is the pinned snapshot URL passed in as CRAN_SNAPSHOT.
#    It is not R's default, and an earlier layer did not change it.
# 4. That URL is a DATED snapshot, not a floating one. It must end in a
#    literal YYYY-MM-DD. So `latest`, or any other moving alias, fails the
#    build here. It cannot re-resolve without notice on a future rebuild.
# 5. The repo RESOLVES: available.packages() returns a full CRAN-sized index
#    (>= 20000 packages) from it. A mistyped or dead snapshot URL returns an
#    empty index, which this catches.
# The build prints the versions of a few well-known packages as the
# fingerprint of the snapshot. The build log then records what "2026
# packages" meant.
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
# The current stable Quarto release when this image was written. The frozen
# stack's Quarto 1.4.550 is two years old. Pinned to an exact version and
# sha256-verified, never `quarto.org/download/latest`, so a rebuild gets the
# same CLI.
RUN curl -fsSL -o /tmp/quarto.deb https://github.com/quarto-dev/quarto-cli/releases/download/v1.9.38/quarto-1.9.38-linux-amd64.deb \
    && echo "bd0d73c1042fc5f719fb87753f0874c11344e516ee2cfbe4fe3ed4e4458c3988  /tmp/quarto.deb" | sha256sum -c - \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/quarto.deb \
    && rm -rf /tmp/quarto.deb /var/lib/apt/lists/* \
    && quarto --version

# --- Optional SSH runtime toggle (off and keyless by default) ---------------
# Same as rbase/4.3.2. openssh-server is installed but INERT. sshd starts
# only if the operator supplies SSH_PUBKEY at `docker run` time (see
# entrypoint.sh). There is no separate "enable" flag, so SSH cannot be on
# with no key. No key of any kind is in this image, and there is no
# password-based login path.
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/*

COPY sshd_hardening.conf /etc/ssh/sshd_config.d/hardening.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Build-time invariant: the EFFECTIVE sshd config disables every
# password-like auth path, root is key-only, AND none of the
# forwarding/tunneling features are available. `sshd -T` never starts the
# daemon, but it needs host keys and /run/sshd to parse and dump the config.
# This layer creates both ONLY for this check and removes them again. So no
# host key is in the image. entrypoint.sh generates a fresh host key per
# CONTAINER at start time.
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
