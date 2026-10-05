# syntax=docker/dockerfile:1
# epirhandbook-reports:2.9: a v2.9 group image for 4 chapters, with 72
# CRAN/Bioc package names. The packages_cran_<stem>.txt files in this
# directory give the chapter membership. epirhandbook/2.9/generate_groups.py
# derives packages_cran.txt from them.
#
# The image is FROM the shared common image. BiocManager, pak and all GitHub
# pins are already in common, so this file does not bootstrap them again. It
# installs the FULL package list of this group on top of common:
# groups/reports/packages_cran.txt. That list is the plain union of the
# full lists of the member chapters (see generate_groups.py). It is not a
# delta with the common packages subtracted. pak finds the packages of
# common already installed and skips them. It resolves only the missing
# hard dependencies (dependencies = NA). Because the full list is
# installed, the final image always holds every package of the group's
# footprint. No step in this build computes a dependency closure by hand.
ARG BASE_IMAGE=epirhandbook-common:2.9
FROM ${BASE_IMAGE}

WORKDIR /home/handbook

COPY pak_install_subset.R pak_install_subset.R
COPY groups/reports/packages_cran.txt packages_cran.txt

RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" \
    Rscript pak_install_subset.R packages_cran.txt \
    && rm -rf /tmp/*

# --- Build-time check: every package in the target list of this group loads.
RUN R -e "targets <- readLines('packages_cran.txt'); targets <- targets[nzchar(targets)]; bad <- targets[!vapply(targets, requireNamespace, logical(1), quietly = TRUE)]; if (length(bad)) { message('LOAD CHECK FAILED (', length(bad), '): ', paste(bad, collapse = ', ')); quit(status = 1L) }; message('LOAD CHECK OK: all ', length(targets), ' target packages load')"
