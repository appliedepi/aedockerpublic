# syntax=docker/dockerfile:1
# epirhandbook-monolith:2.9: the v2.9 monolith image, for all 50 chapters,
# with 320 CRAN/Bioc package names. Its list is the plain union of the 6
# group lists (see epirhandbook/2.9/generate_groups.py). The structure is the
# same as a group Dockerfile. Only the list is different.
#
# The image is FROM the shared common image. BiocManager, pak and all GitHub
# pins are already in common, so this file does not bootstrap them again. It
# installs the FULL package list of the monolith, monolith/packages_cran.txt,
# on top of common. It is not a delta with the common packages subtracted.
# pak finds the packages of common already installed and skips them. It
# resolves only the missing hard dependencies (dependencies = NA). Because
# the full list is installed, the final image always holds every package of
# the footprint of the whole book. No step in this build computes a
# dependency closure by hand.
ARG BASE_IMAGE=epirhandbook-common:2.9
FROM ${BASE_IMAGE}

WORKDIR /home/handbook

COPY pak_install_subset.R pak_install_subset.R
COPY monolith/packages_cran.txt packages_cran.txt

RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" \
    Rscript pak_install_subset.R packages_cran.txt \
    && rm -rf /tmp/*

# --- Build-time check: every package in the target list of the monolith loads.
RUN R -e "targets <- readLines('packages_cran.txt'); targets <- targets[nzchar(targets)]; bad <- targets[!vapply(targets, requireNamespace, logical(1), quietly = TRUE)]; if (length(bad)) { message('LOAD CHECK FAILED (', length(bad), '): ', paste(bad, collapse = ', ')); quit(status = 1L) }; message('LOAD CHECK OK: all ', length(targets), ' target packages load')"
