# syntax=docker/dockerfile:1
# rbase:4.3.2 — Applied Epi own R base image (R 4.3.2, Ubuntu jammy)
# (named rbase, not base, to leave room for a separate pythonbase later)
#
# SELF-OWNED: `FROM ubuntu:jammy` + R installed from Posit's public r-builds .deb
# — NO dependency on the rocker project. Pattern adapted from niphr/cs
# (github.com/niphr/cs, 1-rbase/Dockerfile). This is the Posit-.deb path, not a
# from-source R compile (same choice niphr makes); it still owns the whole image.
#
# rbase carries the OS toolchain that is stable across products: R 4.3.2, the
# handbook CI's system libraries, the compilers, the JDK, and Quarto 1.4.550. It
# installs NO R packages — each product image layers its own set on top
# (epirhandbook/2.5 restores the 473 renv.lock packages via pak).
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
# The handbook's own CI apt list (render_book_on_pr.yml:42), MINUS the two ubuntu
# R packages `r-base-dev` and `r-cran-rjava`: on bare ubuntu those pull ubuntu's
# own R (r-base-core 4.1.2), which would collide with the Posit R 4.3.2 below. We
# keep openjdk-11-jdk (rJava + OpenStreetMap in the lock build against it via
# `R CMD javareconf`), and add the toolchain rocker preinstalls but bare ubuntu
# lacks: a C/C++/Fortran compiler (build-essential, gfortran), cmake (nloptr's
# NLopt), and — critically — libopenblas0-pthread, the SAME BLAS/LAPACK
# (openblas-pthread 0.3.20) rocker/r-ver:4.3.2 links, so compiled numerics match
# the Phase-1 render. libgsl-dev is for SemiCompRisks.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl gnupg \
    build-essential gfortran cmake pkg-config \
    zlib1g-dev libbz2-dev liblzma-dev libpcre2-dev libicu-dev \
    libopenblas0-pthread \
    openjdk-11-jdk \
    libcurl4-openssl-dev libxml2-dev libssl-dev libfontconfig1-dev libharfbuzz-dev libfribidi-dev libfreetype6-dev libpng-dev libtiff5-dev libjpeg-dev libglpk-dev gdal-bin libgdal-dev libxslt1-dev libgit2-dev libgeos-dev libproj-dev libudunits2-dev libcairo2-dev libxt-dev libmagick++-dev libpoppler-cpp-dev libpq-dev libmysqlclient-dev libsqlite3-dev libssh2-1-dev libgmp3-dev libmpfr-dev libprotobuf-dev protobuf-compiler libgl1-mesa-dev libglu1-mesa-dev libpoppler-glib-dev libtbb-dev libsodium-dev libv8-dev libnetcdf-dev netcdf-bin libjq-dev libnode-dev jq \
    libgsl-dev \
    && rm -rf /var/lib/apt/lists/*

# Force the BLAS/LAPACK alternatives to openblas-pthread (match rocker exactly).
RUN update-alternatives --set "libblas.so.3-$(uname -m)-linux-gnu" "/usr/lib/$(uname -m)-linux-gnu/openblas-pthread/libblas.so.3" \
    && update-alternatives --set "liblapack.so.3-$(uname -m)-linux-gnu" "/usr/lib/$(uname -m)-linux-gnu/openblas-pthread/liblapack.so.3"

# --- R 4.3.2 from Posit r-builds (NOT rocker) -------------------------------
# Posit's prebuilt R .deb installs into /opt/R/${R_VERSION}; `apt-get install -f`
# resolves R's runtime deps. Symlink R/Rscript onto PATH, then javareconf wires R
# to the JDK for rJava.
RUN wget --tries=5 --retry-connrefused --waitretry=10 -q \
      -O /tmp/R.deb "https://cdn.rstudio.com/r/ubuntu-2204/pkgs/r-${R_VERSION}_1_amd64.deb" \
    && apt-get update \
    && apt-get install -f -y --no-install-recommends /tmp/R.deb \
    && ln -s /opt/R/${R_VERSION}/bin/R /usr/local/bin/R \
    && ln -s /opt/R/${R_VERSION}/bin/Rscript /usr/local/bin/Rscript \
    && rm /tmp/R.deb && rm -rf /var/lib/apt/lists/*
RUN R CMD javareconf

# Build-time invariant: R is the expected version AND its BLAS/LAPACK is
# openblas-pthread (so numerics match the Phase-1 rocker render). Fails the base
# build if the version or the BLAS alternative is wrong.
RUN R -e "stopifnot(getRversion() == '${R_VERSION}'); si <- sessionInfo(); cat('R', as.character(getRversion()), '| BLAS', si[['BLAS']], '| LAPACK', si[['LAPACK']], '\n'); stopifnot(grepl('openblas', si[['BLAS']], ignore.case = TRUE), grepl('openblas', si[['LAPACK']], ignore.case = TRUE))"

# --- Quarto CLI 1.4.550 (the version the handbook CI rendered with) ---------
RUN curl -fsSL -o /tmp/quarto.deb https://github.com/quarto-dev/quarto-cli/releases/download/v1.4.550/quarto-1.4.550-linux-amd64.deb \
    && echo "5ba82c811f5b12d9e8fa2f45ff306dca2f82472d6944104678c5294a02883164  /tmp/quarto.deb" | sha256sum -c - \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/quarto.deb \
    && rm -rf /tmp/quarto.deb /var/lib/apt/lists/*

# Phase 4 will add the optional openssh-server (runtime-toggled) here.
