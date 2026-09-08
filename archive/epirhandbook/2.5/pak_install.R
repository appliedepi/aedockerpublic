#!/usr/bin/env Rscript
# Phase 2 installer: restore the 473 renv.lock packages with pak, at their
# EXACT locked versions/SHAs. A rehearsal of pak's machinery on a known-good pin
# set (a test of pak, not a re-pin), replacing Phase 1's renv::restore(). The
# rendered book must come out identical to Phase 1.
#
# pak does not read renv.lock natively (its lockfile_* functions are pak's own
# pkg.lock format), so we translate the lock into explicit pak refs, one per
# package, and install the closed set. renv.lock stays the single source of
# truth; nothing here is hand-pinned. The INSTALLED version is always the lock's
# pin — the ref FORM below only changes how each package is fetched.
#
# Why not just `pkg@version` for every CRAN package? Because it is 2026 and
# CRAN-HEAD versions of many packages now require R >= 4.4, while this image is
# frozen at R 4.3.2. pak's SAT solver evaluates the CURRENT version's R
# constraint even when an older version is pinned, and then reports a spurious
# "dependency conflict" (seen on BH, bitops, rapidjsonr, KMsurv and the
# recommended packages MASS/nnet/survival/nlme/lattice/boot/class/rpart/
# KernSmooth/codetools). renv never hits this because it does not solve — it
# just installs the pinned tarball. So we do the same for any pin that is not
# the current CRAN release: address it as an explicit `url::` archive tarball,
# which bypasses the solver. Pins that DO equal the current release resolve
# cleanly as `pkg@version` (their current version supports R 4.3.2, or the lock
# could not have pinned it).
#
# Ref forms (all validated to resolve the full 473-set with no conflict):
#   - CRAN, pinned == current release -> "pkg@version"
#   - CRAN, pinned != current release -> "url::<cloud Archive tarball>"
#   - GitHub                          -> "github::user/repo@sha"  (needs GITHUB_PAT)
#   - Bioconductor                    -> "url::<exact bioc tarball>"

lock <- jsonlite::fromJSON("renv.lock", simplifyVector = FALSE)
pkgs <- lock$Packages

# Source-only CRAN repo (incl. its /src/contrib/Archive): matches Phase 1's
# source compile, so the only variable vs Phase 1 is the installer (renv -> pak),
# not a source-vs-binary axis. Set before available.packages() so it reads here.
options(repos = c(CRAN = "https://cloud.r-project.org"))

# Current CRAN release per package, used ONLY to route pkg@version vs url::
# (not to choose the version — that is always the lock's pin).
ap <- available.packages(repos = "https://cloud.r-project.org")
current_ver <- function(pkg) {
  if (pkg %in% rownames(ap)) ap[pkg, "Version"] else NA_character_
}

cran_ref <- function(name, ver) {
  cur <- current_ver(name)
  if (!is.na(cur) && identical(cur, ver)) {
    sprintf("%s@%s", name, ver)
  } else {
    sprintf(
      "url::https://cloud.r-project.org/src/contrib/Archive/%s/%s_%s.tar.gz",
      name,
      name,
      ver
    )
  }
}

# Bioconductor: address each package as its exact tarball. A frozen Bioc release
# keeps its CURRENT patch in src/contrib and moves older patches to
# Archive/<pkg>/, and the lock can pin either (e.g. ggtree 3.10.0 is pinned but
# the 3.18 contrib dir now serves 3.10.1 — only Archive still has 3.10.0), so
# probe contrib first, fall back to Archive, and fail loudly if neither exists.
# The contrib base is taken from the lock's own BioCsoft repo.
biocsoft <- Filter(function(r) r$Name == "BioCsoft", lock$R$Repositories)[[
  1
]]$URL
bioc_contrib <- paste0(biocsoft, "/src/contrib")
http_status <- function(u) {
  st <- tryCatch(
    attr(curlGetHeaders(u, timeout = 30L), "status"),
    error = function(e) NA_integer_
  )
  if (is.null(st)) NA_integer_ else as.integer(st)
}
bioc_url <- function(pkg, ver) {
  contrib <- sprintf("%s/%s_%s.tar.gz", bioc_contrib, pkg, ver)
  archive <- sprintf("%s/Archive/%s/%s_%s.tar.gz", bioc_contrib, pkg, pkg, ver)
  if (identical(http_status(contrib), 200L)) {
    return(contrib)
  }
  if (identical(http_status(archive), 200L)) {
    return(archive)
  }
  stop(sprintf(
    "Bioc tarball not found for %s %s (tried contrib and Archive)",
    pkg,
    ver
  ))
}

ref_for <- function(name, p) {
  switch(
    p$Source,
    Repository = cran_ref(name, p$Version),
    GitHub = sprintf(
      "github::%s/%s@%s",
      p$RemoteUsername,
      p$RemoteRepo,
      p$RemoteSha
    ),
    Bioconductor = sprintf("url::%s", bioc_url(name, p$Version)),
    stop(sprintf("unhandled Source '%s' for package %s", p$Source, name))
  )
}

refs <- vapply(names(pkgs), function(n) ref_for(n, pkgs[[n]]), character(1))

# Audit trail in the build log: counts by ref form + the small, verifiable sets.
cat(sprintf(
  "Generated %d refs: %d url:: | %d github:: | %d pkg@version\n",
  length(refs),
  sum(grepl("^url::", refs)),
  sum(grepl("^github::", refs)),
  sum(!grepl("^(url|github)::", refs))
))
cat("GitHub refs:\n")
print(unname(grep("^github::", refs, value = TRUE)))
cat("Bioconductor url:: refs:\n")
print(unname(grep("/bioc/src/contrib/", refs, value = TRUE)))
cat("First 5 CRAN url:: refs:\n")
print(unname(head(
  grep(
    "^url::.*/cran|/src/contrib/Archive",
    grep("bioc", refs, value = TRUE, invert = TRUE),
    value = TRUE
  ),
  5
)))

# --- Install in topological layers ------------------------------------------
# pak has no "install this EXACT set in dependency order without re-solving" mode,
# and that is precisely what we need:
#   - dependencies = FALSE keeps the solver off (required: the url:: pins would
#     otherwise hit the R >= 4.4 conflict) but DROPS the build-order edges, so pak
#     builds all 473 in parallel and a source package can build before an in-set
#     build dependency is installed (RcppRoll before Rcpp, DT before its imports
#     -> "dependency X is not available for package Y").
#   - dependencies = NA restores ordering but re-activates the solver and the
#     R >= 4.4 conflict on 35+ packages. So NA is not the fix either.
# Impose the order ourselves from the lock's OWN Requirements (the same edges renv
# installs by): sort the closure into layers where every package's in-set
# requirements are already installed, and install each layer with
# dependencies = FALSE. Within a layer packages are mutually independent so pak
# still parallelises; across layers the order is guaranteed. No solver, exact
# versions, correct build order. pak does not set MAKEFLAGS=-jN, so the Phase-1
# frailtypack race does not apply. The per-layer retry covers transient download
# blips (install is incremental).
deps <- lapply(pkgs, function(p) intersect(unlist(p$Requirements), names(pkgs)))

install_layer <- function(layer_refs) {
  for (attempt in 1:2) {
    ok <- tryCatch(
      {
        pak::pkg_install(layer_refs, dependencies = FALSE, ask = FALSE)
        TRUE
      },
      error = function(e) {
        message("layer attempt ", attempt, " failed: ", conditionMessage(e))
        FALSE
      }
    )
    if (isTRUE(ok)) {
      return(invisible())
    }
    message("retry in 20s")
    Sys.sleep(20)
  }
  quit(status = 1L)
}

done <- character(0)
remaining <- names(pkgs)
layer_no <- 0L
while (length(remaining)) {
  ready <- remaining[vapply(
    remaining,
    function(n) all(deps[[n]] %in% done),
    logical(1)
  )]
  if (!length(ready)) {
    stop(
      "dependency cycle among locked packages: ",
      paste(utils::head(remaining, 10), collapse = ", ")
    )
  }
  layer_no <- layer_no + 1L
  cat(sprintf(
    "Layer %d: %d packages (%d installed, %d remaining)\n",
    layer_no,
    length(ready),
    length(done),
    length(remaining) - length(ready)
  ))
  install_layer(unname(refs[ready]))
  done <- c(done, ready)
  remaining <- setdiff(remaining, ready)
}
cat(sprintf(
  "pak install complete: %d packages in %d layers.\n",
  length(done),
  layer_no
))
