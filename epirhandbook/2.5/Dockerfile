# syntax=docker/dockerfile:1
# epirhandbook:2.5 — Phase 2 (factor + pak rehearsal)
#
# Splits the Phase 1 monolith into our own rbase:4.3.2 (OS + sysdeps + Quarto)
# plus this thin product image, and swaps the installer renv::restore() -> pak.
# pak is driven by the EXACT renv.lock pins (same versions/SHAs) via
# pak_install.R — a test of pak's machinery, not a re-pin. The rendered book
# must come out identical to Phase 1 (regression bar: verify/manifest.tsv).
#
# BASE_IMAGE defaults to the floating local tag for a plain local build
# (`docker build -t epirhandbook:2.5 epirhandbook/2.5` still works exactly
# as documented in README.md, using whatever rbase:4.3.2 is on the local
# machine). CI overrides it with a DIGEST pin
# (ghcr.io/appliedepi/aedockerpublic/rbase@sha256:...), never a floating
# tag -- see images.yaml's "Digest-pinning procedure" for how that digest is
# obtained and kept in sync, and why a floating tag is not safe to publish
# against (it can move to a different rbase build after this image is
# published, silently changing what a "pull and run" gets).
ARG BASE_IMAGE=rbase:4.3.2
FROM ${BASE_IMAGE}

WORKDIR /home/handbook

# --- pak + jsonlite bootstrap -----------------------------------------------
# pak >= 0.11.0 as a binary from the current PPM jammy index (fast). pak is a
# BUILD tool: its version does not affect the rendered output — the pins that
# govern reproducibility are the 473 package refs, resolved independently of
# pak's version. So pak is not itself date-frozen (a dated snapshot risks a
# not-yet-cut date failing the build); the `>=` guard just floors it at the
# version whose ref behaviour (url::/github::/pkg@version) was validated.
# jsonlite is bootstrapped alongside pak because pak_install.R AND the final
# version check parse renv.lock with jsonlite::fromJSON, yet base carries no R
# packages and pak vendors its own jsonlite privately (not loadable as
# jsonlite::). Like pak it is an unpinned build tool here — nothing hand-pinned;
# pak_install.R installs the LOCKED jsonlite (1.8.8) as one of the 473, so the
# final image still carries the pinned version.
RUN R -e "install.packages(c('pak', 'jsonlite'), repos = 'https://packagemanager.posit.co/cran/__linux__/jammy/latest'); stopifnot(packageVersion('pak') >= '0.11.0', requireNamespace('jsonlite', quietly = TRUE))"

COPY renv.lock renv.lock
COPY pak_install.R pak_install.R

# --- Restore all 473 packages at exact versions, from source, via pak -------
# pak_install.R translates renv.lock into explicit pak refs (CRAN pinned==current
# as pkg@version; archived CRAN + Bioconductor as url::<exact tarball>; GitHub as
# github::user/repo@sha) and installs the closed set from source (CRAN pointed at
# cloud.r-project.org, overriding the base image's PPM default), so the only
# variable vs Phase 1 is the installer itself. The url:: form for archived pins
# bypasses pak's SAT solver, which otherwise rejects them because CRAN-HEAD now
# needs R >= 4.4 while this image is frozen at 4.3.2 (see pak_install.R).
#
# GITHUB_PAT (needed to resolve the 7 GitHub-SHA-pinned packages without hitting
# the unauthenticated GitHub API rate limit) is a BuildKit SECRET, mounted only
# for this RUN. It is deliberately NOT ARG+ENV: an ENV bakes the token into the
# image Config.Env, where docker inspect leaks it — unacceptable for a public
# image. A secret mount never touches any layer or the build history.
# --mount=type=cache persists pak's download/build cache across separate
# `docker build` runs, so a rebuild after a fix reuses already-compiled packages
# instead of recompiling all 473 from scratch.
# The trailing `rm -rf /tmp/*` runs in THIS layer so pak's build scratch (R
# session tempdirs — ~4 GB of unpacked sources and .o/.so left from compiling
# 473 packages, which R does not auto-clean here) is NOT committed into the
# image. The durable cache lives in the /root/.cache/R mount (outside the image)
# and the packages in site-library, so /tmp holds only disposable cruft; leaving
# it in doubled the image (9.5 GB -> ~5 GB after cleanup).
RUN --mount=type=cache,target=/root/.cache/R --mount=type=secret,id=github_pat \
    GITHUB_PAT="$(cat /run/secrets/github_pat 2>/dev/null)" Rscript pak_install.R \
    && rm -rf /tmp/*

# --- Build-time invariant: every locked package LOADS and is at its EXACT -----
# --- locked version ----------------------------------------------------------
# Stronger than Phase 1's load-only check: also asserting the installed version
# equals the lock would have caught the ggtree 3.10.0 -> 3.10.1 Bioconductor
# drift (Phase 1's requireNamespace-only check passes either way). requireNamespace
# loads each namespace and its shared libraries without attaching; the version
# comparison uses numeric_version equality (robust to 1.84.0-0 / 0.0.0.9000
# forms). Any missing package or version mismatch fails the build. Uses [[ ]]
# (exact) not $ so no shell/$ escaping is needed and no partial-name matching.
RUN R -e "lock <- jsonlite::fromJSON('renv.lock', simplifyVector = FALSE); pkgs <- lock[['Packages']]; bad <- character(0); for (n in names(pkgs)) { if (!requireNamespace(n, quietly = TRUE)) { bad <- c(bad, paste0(n, ': FAILS TO LOAD')); next }; if (packageVersion(n) != pkgs[[n]][['Version']]) bad <- c(bad, sprintf('%s: installed %s != locked %s', n, as.character(packageVersion(n)), pkgs[[n]][['Version']])) }; if (length(bad)) { message('VERSION/LOAD CHECK FAILED (', length(bad), '):'); message(paste(bad, collapse = '\n')); quit(status = 1L) }; message('VERSION/LOAD CHECK OK: all ', length(pkgs), ' packages load at exact locked versions')"
