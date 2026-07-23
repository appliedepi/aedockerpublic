#!/usr/bin/env Rscript
# Phase 5a installer: installs a SUBSET of renv.lock's packages, at their
# EXACT locked versions/SHAs, via pak. Adapted from Phase 2's
# epirhandbook/2.5/pak_install.R -- same ref-construction logic (CRAN pinned
# == current release -> pkg@version; CRAN pinned != current, or Bioconductor
# -> url::<archive tarball>; GitHub -> github::user/repo@sha) and the same
# topological-layered dependencies=FALSE install, required to avoid pak's SAT
# solver rejecting an archived CRAN pin whose CURRENT release now needs
# R >= 4.4 (this image is frozen at R 4.3.2) -- see pak_install.R's own header
# for the full story; nothing about that trap changes here.
#
# THE ONLY DIFFERENCE FROM pak_install.R: this script installs only the
# packages named in a target-list file (one package name per line), not all
# 473. That list is expected to already be CLOSURE-EXPANDED -- every named
# package's own transitive Requirements (per renv.lock), already included --
# because generate.py computes that closure once, in Python, at generation
# time (over the SAME renv.lock Requirements graph pak_install.R's own `deps`
# map already walks for the full 473-package install). This script does not
# recompute the closure; it re-verifies it (see the closure self-check below)
# and then subsets renv.lock$Packages to exactly those names and installs
# them in dependency order, exactly like pak_install.R does for the full set.
#
# WHY A CLOSURE, NOT THE RAW loadedNamespaces() FOOTPRINT: a chapter's
# footprint (chapters/footprints.tsv) is an EMPIRICAL record of what a render
# actually loaded when every other package was ALSO available (Phase 3
# README.md says this explicitly). It is not install-complete -- an R package
# can access another via a `pkg::fun()` call without an eager NAMESPACE
# import, so the *lazily*-touched dependency does show up in
# loadedNamespaces() (e.g. ggplot2's `isoband` only appears for chapters that
# actually draw a contour), but a *build-time-only* dependency (a compiled
# package's LinkingTo header, or a DESCRIPTION Import touched by a code path
# the chapter's own content never exercises) can be entirely invisible to
# loadedNamespaces() while still being required to INSTALL the footprint's
# own packages from source. Installing the raw footprint alone, with
# dependencies=FALSE (required -- see above), would then fail outright:
# "dependency X is not available for package Y" -- the exact failure
# pak_install.R's own header already documents for the full-473 case. Closure-
# expanding via renv.lock's Requirements field (Imports+Depends+LinkingTo, per
# this project's renv/settings.json `package.dependency.fields`) is the same
# real build-order graph renv itself installed by, and pak_install.R already
# leans on for the full 473 -- this script only ever walks a SUBSET of that
# same graph.
#
# Usage: Rscript pak_install_subset.R <packages.txt>

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) {
  stop("usage: Rscript pak_install_subset.R <packages.txt>")
}
target_file <- args[[1]]
target_names <- readLines(target_file)
target_names <- target_names[nzchar(trimws(target_names))]
target_names <- unique(target_names)

lock <- jsonlite::fromJSON("renv.lock", simplifyVector = FALSE)
all_pkgs <- lock$Packages

missing <- setdiff(target_names, names(all_pkgs))
if (length(missing)) {
  stop(sprintf(
    "%s names %d package(s) not present in renv.lock (typo, or renv.lock drifted from the one generate.py read): %s",
    target_file,
    length(missing),
    paste(missing, collapse = ", ")
  ))
}

# Closure self-check: every package in target_names must have every one of
# its OWN Requirements (that is itself a real locked package) ALSO present in
# target_names. generate.py is expected to have already closure-expanded the
# list; this re-derives the same check independently, inside the installer,
# so a bug in the generator (or a hand-edited packages.txt) is caught here,
# loudly, before any download/compile happens -- not discovered 40 minutes
# into a build as a "dependency X is not available" pak error.
target_set <- target_names
gaps <- list()
for (n in target_names) {
  reqs <- intersect(unlist(all_pkgs[[n]]$Requirements), names(all_pkgs))
  missing_reqs <- setdiff(reqs, target_set)
  if (length(missing_reqs)) {
    gaps[[n]] <- missing_reqs
  }
}
if (length(gaps)) {
  msg <- paste(
    sprintf(
      "  %s needs: %s",
      names(gaps),
      vapply(gaps, paste, character(1), collapse = ", ")
    ),
    collapse = "\n"
  )
  stop(sprintf(
    "%s is NOT closure-complete -- %d package(s) have a Requirement missing from the target list:\n%s",
    target_file,
    length(gaps),
    msg
  ))
}

pkgs <- all_pkgs[target_names]
cat(sprintf(
  "Target set: %d packages (closure self-check passed).\n",
  length(pkgs)
))

# Source-only CRAN repo (incl. its /src/contrib/Archive): matches Phase 1/2's
# source compile, so the only variable vs Phase 2 is WHICH packages get
# installed, not a source-vs-binary axis. Set before available.packages() so
# it reads here.
options(repos = c(CRAN = "https://cloud.r-project.org"))

# Current CRAN release per package, used ONLY to route pkg@version vs url::
# (not to choose the version -- that is always the lock's pin). Identical to
# pak_install.R.
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

# Bioconductor: identical to pak_install.R -- probe contrib first, fall back
# to Archive, fail loudly if neither exists.
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

# --- Install in topological layers (identical strategy to pak_install.R) ---
# dependencies = FALSE keeps pak's solver off (required: the url:: pins would
# otherwise hit the R >= 4.4 conflict); the topological layering from the
# lock's own Requirements restores build order without it. Because
# target_names is already closure-complete (verified above), every layer's
# requirements resolve from WITHIN this same subset -- nothing here needs to
# reach outside pkgs.
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
      "dependency cycle among target packages: ",
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
