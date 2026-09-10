# syntax=docker/dockerfile:1
# epirhandbook-basics:2.9 -- v2.9 group image (8 chapters, 62
# CRAN/Bioc package names -- see epirhandbook/2.9/groups.yaml for the exact
# chapter membership and epirhandbook/2.9/generate_groups.py for how
# packages_cran.txt below was derived).
#
# FROM the shared common image (BiocManager, pak, and all GitHub pins
# already present there -- no re-bootstrap here). Installs THIS GROUP's own
# FULL package list (groups/basics/packages_cran.txt, the plain union of
# its member chapters' own full lists -- see generate_groups.py) on top
# of common, not a pre-subtracted delta: pak sees common's packages already
# present and skips them (dependencies = NA only resolves what's missing),
# so installing the full list here is what makes the final image a strict
# superset of the group's footprint BY CONSTRUCTION, with no hand-computed
# closure anywhere in this build.
ARG BASE_IMAGE=epirhandbook-common:2.9
FROM ${BASE_IMAGE}

WORKDIR /home/handbook

COPY pak_install_subset.R pak_install_subset.R
COPY groups/basics/packages_cran.txt packages_cran.txt

RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" \
    Rscript pak_install_subset.R packages_cran.txt \
    && rm -rf /tmp/*

# --- Build-time invariant, restricted to this group's own target list ------
RUN R -e "targets <- readLines('packages_cran.txt'); targets <- targets[nzchar(targets)]; bad <- targets[!vapply(targets, requireNamespace, logical(1), quietly = TRUE)]; if (length(bad)) { message('LOAD CHECK FAILED (', length(bad), '): ', paste(bad, collapse = ', ')); quit(status = 1L) }; message('LOAD CHECK OK: all ', length(targets), ' target packages load')"
