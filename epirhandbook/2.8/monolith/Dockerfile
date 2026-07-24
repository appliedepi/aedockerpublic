# syntax=docker/dockerfile:1
# epirhandbook-monolith:2.8 -- v2.8 monolith image: all 49 chapters, 298
# CRAN/Bioc package names -- the plain union of the 6 group lists (see
# epirhandbook/2.8/generate_groups.py). Structurally identical to a group
# Dockerfile; its list simply happens to be the union of all six.
#
# FROM the shared common image (BiocManager, pak, and all 9 GitHub pins
# already present there -- no re-bootstrap here). Installs the monolith's own
# FULL package list (monolith/packages_cran.txt) on top of common, not
# a pre-subtracted delta: pak sees common's packages already present and
# skips them (dependencies = NA only resolves what's missing), so installing
# the full list here is what makes the final image a strict superset of the
# whole book's footprint BY CONSTRUCTION, with no hand-computed closure
# anywhere in this build -- same pattern as
# epirhandbook/2.7/chapters/*/Dockerfile.
ARG BASE_IMAGE=epirhandbook-common:2.8
FROM ${BASE_IMAGE}

WORKDIR /home/handbook

COPY pak_install_subset.R pak_install_subset.R
COPY monolith/packages_cran.txt packages_cran.txt

RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" \
    Rscript pak_install_subset.R packages_cran.txt \
    && rm -rf /tmp/*

# --- Build-time invariant, restricted to the monolith's own target list ----
RUN R -e "targets <- readLines('packages_cran.txt'); targets <- targets[nzchar(targets)]; bad <- targets[!vapply(targets, requireNamespace, logical(1), quietly = TRUE)]; if (length(bad)) { message('LOAD CHECK FAILED (', length(bad), '): ', paste(bad, collapse = ', ')); quit(status = 1L) }; message('LOAD CHECK OK: all ', length(targets), ' target packages load')"
