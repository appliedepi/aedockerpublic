# syntax=docker/dockerfile:1
# rbase:4.3.2: the Applied Epi R base image (R 4.3.2, Ubuntu jammy)
# (named rbase, not base, to leave room for a separate pythonbase later)
#
# SELF-OWNED: `FROM ubuntu:jammy` plus R from Posit's public r-builds .deb,
# with NO dependency on the rocker project. The pattern comes from niphr/cs
# (github.com/niphr/cs, 1-rbase/Dockerfile). It uses the Posit .deb, not a
# from-source R compile (the same choice as niphr). This repo still owns the
# whole image.
#
# rbase carries the OS toolchain that is stable across products. That is R
# 4.3.2, the handbook CI's system libraries, the compilers, the JDK, and
# Quarto 1.4.550. It installs NO R packages. Each product image adds its own
# set on top (epirhandbook/2.5 restores the 473 renv.lock packages via pak).
#
# Ubuntu pinned by DIGEST (immutable) for reproducibility.
FROM ubuntu:jammy@sha256:0e0a0fc6d18feda9db1590da249ac93e8d5abfea8f4c3c0c849ce512b5ef8982

ARG R_VERSION=4.3.2
ENV R_VERSION=${R_VERSION}
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

# apt: resilient to transient network blips
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80-retries

# --- Locale (handbook content is UTF-8) -------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends locales \
    && locale-gen en_US.UTF-8 && rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV LANGUAGE=en_US:en

# --- System dependencies ----------------------------------------------------
# The handbook's own CI apt list (render_book_on_pr.yml:42), MINUS the two
# ubuntu R packages `r-base-dev` and `r-cran-rjava`. On bare ubuntu those
# pull ubuntu's own R (r-base-core 4.1.2), which would collide with the Posit
# R 4.3.2 below. Other choices:
#   - openjdk-11-jdk stays. rJava and OpenStreetMap in the lock build against
#     it via `R CMD javareconf`.
#   - The list adds the toolchain that rocker preinstalls and bare ubuntu
#     lacks: a C/C++/Fortran compiler (build-essential, gfortran) and cmake
#     (for the NLopt of nloptr).
#   - It adds libopenblas0-pthread, the SAME BLAS/LAPACK (openblas-pthread
#     0.3.20) that rocker/r-ver:4.3.2 links. Compiled numerics then match the
#     Phase-1 render.
#   - libgsl-dev is for SemiCompRisks.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl gnupg \
    build-essential gfortran cmake pkg-config \
    zlib1g-dev libbz2-dev liblzma-dev libpcre2-dev libicu-dev \
    libopenblas0-pthread \
    openjdk-11-jdk \
    libcurl4-openssl-dev libxml2-dev libssl-dev libfontconfig1-dev libharfbuzz-dev libfribidi-dev libfreetype6-dev libpng-dev libtiff5-dev libjpeg-dev libglpk-dev gdal-bin libgdal-dev libxslt1-dev libgit2-dev libgeos-dev libproj-dev libudunits2-dev libcairo2-dev libxt-dev libmagick++-dev libpoppler-cpp-dev libpq-dev libmysqlclient-dev libsqlite3-dev libssh2-1-dev libgmp3-dev libmpfr-dev libprotobuf-dev protobuf-compiler libgl1-mesa-dev libglu1-mesa-dev libpoppler-glib-dev libtbb-dev libsodium-dev libv8-dev libnetcdf-dev netcdf-bin libjq-dev libnode-dev jq \
    libgsl-dev \
    && rm -rf /var/lib/apt/lists/*

# Force the BLAS/LAPACK alternatives to openblas-pthread, the same as rocker.
RUN update-alternatives --set "libblas.so.3-$(uname -m)-linux-gnu" "/usr/lib/$(uname -m)-linux-gnu/openblas-pthread/libblas.so.3" \
    && update-alternatives --set "liblapack.so.3-$(uname -m)-linux-gnu" "/usr/lib/$(uname -m)-linux-gnu/openblas-pthread/liblapack.so.3"

# --- R 4.3.2 from Posit r-builds (NOT rocker) -------------------------------
# Posit's prebuilt R .deb installs into /opt/R/${R_VERSION}. `apt-get install
# -f` resolves R's runtime deps. The R/Rscript symlinks go onto PATH. Then
# javareconf connects R to the JDK for rJava.
RUN wget --tries=5 --retry-connrefused --waitretry=10 -q \
      -O /tmp/R.deb "https://cdn.rstudio.com/r/ubuntu-2204/pkgs/r-${R_VERSION}_1_amd64.deb" \
    && apt-get update \
    && apt-get install -f -y --no-install-recommends /tmp/R.deb \
    && ln -s /opt/R/${R_VERSION}/bin/R /usr/local/bin/R \
    && ln -s /opt/R/${R_VERSION}/bin/Rscript /usr/local/bin/Rscript \
    && rm /tmp/R.deb && rm -rf /var/lib/apt/lists/*
RUN R CMD javareconf

# Build-time invariant: R is the expected version AND its BLAS/LAPACK is
# openblas-pthread, so numerics match the Phase-1 rocker render. The base
# build fails if the version or the BLAS alternative is wrong.
RUN R -e "stopifnot(getRversion() == '${R_VERSION}'); si <- sessionInfo(); cat('R', as.character(getRversion()), '| BLAS', si[['BLAS']], '| LAPACK', si[['LAPACK']], '\n'); stopifnot(grepl('openblas', si[['BLAS']], ignore.case = TRUE), grepl('openblas', si[['LAPACK']], ignore.case = TRUE))"

# --- Quarto CLI 1.4.550 (the version the handbook CI rendered with) ---------
RUN curl -fsSL -o /tmp/quarto.deb https://github.com/quarto-dev/quarto-cli/releases/download/v1.4.550/quarto-1.4.550-linux-amd64.deb \
    && echo "5ba82c811f5b12d9e8fa2f45ff306dca2f82472d6944104678c5294a02883164  /tmp/quarto.deb" | sha256sum -c - \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/quarto.deb \
    && rm -rf /tmp/quarto.deb /var/lib/apt/lists/*

# --- Optional SSH runtime toggle (off and keyless by default) ---------------
# openssh-server is installed but INERT. sshd starts only if the operator
# supplies SSH_PUBKEY at `docker run` time (see entrypoint.sh). There is no
# separate "enable" flag, so SSH cannot be on with no key. No key of any
# kind is in this image, and there is no password-based login path. The
# check below enforces this, and sshd_hardening.conf enforces it again at
# runtime.
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/*

COPY sshd_hardening.conf /etc/ssh/sshd_config.d/hardening.conf
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Build-time invariant: the EFFECTIVE sshd config disables every
# password-like auth path, root is key-only, AND (Phase 4 / finding 9) none
# of the forwarding/tunneling features are available. `sshd -T` never starts
# the daemon, but it needs host keys and /run/sshd to parse and dump the
# config. Without them it exits 255 with "no hostkeys available" (observed
# when tested). This layer creates both ONLY for this check and removes them
# again. So no host key is in the image. entrypoint.sh generates a fresh
# host key per CONTAINER at start time. `sshd -T` prints PermitRootLogin's
# `prohibit-password` as its alias `without-password`, so the check matches
# that form.
RUN ssh-keygen -A \
    && mkdir -p /run/sshd \
    && CFG="$(/usr/sbin/sshd -T)" \
    && echo "$CFG" | grep -qx 'passwordauthentication no' \
    && echo "$CFG" | grep -qx 'kbdinteractiveauthentication no' \
    && echo "$CFG" | grep -qx 'permitemptypasswords no' \
    && echo "$CFG" | grep -qx 'permitrootlogin without-password' \
    && echo "$CFG" | grep -qx 'allowtcpforwarding no' \
    && echo "$CFG" | grep -qx 'x11forwarding no' \
    && echo "$CFG" | grep -qx 'permittunnel no' \
    && echo "$CFG" | grep -qx 'gatewayports no' \
    && echo "$CFG" | grep -qx 'allowagentforwarding no' \
    && rm -rf /etc/ssh/ssh_host_* /run/sshd

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/bin/bash"]
