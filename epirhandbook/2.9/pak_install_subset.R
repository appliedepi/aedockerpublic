#!/usr/bin/env Rscript
# Phase 5b installer. It installs the MAIN packages of an image, and pak
# resolves the full dependency tree from the pinned sources. There are two
# inputs, split by how each package is pinned:
#
#   packages_cran.txt    One package NAME per line. These are CRAN and
#                        Bioconductor packages, installed by bare name.
#                        Required.
#   packages_github.json The GitHub packages, each with a commit SHA.
#                        Optional. Only the `common` Dockerfile passes it.
#                        common installs all the GitHub pins once, so every
#                        image FROM common inherits them. A transitive
#                        dependency then uses the pin, and pak does not
#                        resolve that package from CRAN.
#
# Each source has one place that pins it. No dependency graph is computed by
# hand:
#   CRAN    The dated PPM snapshot gives the versions. The rbase tag owns the
#           snapshot, and this script INHERITS it via getOption("repos").
#           This script does not assert a version.
#   Bioc    The release paired with R (BiocManager::version()). It comes from
#           the R version, so no second file stores it.
#   GitHub  A commit SHA for each package (packages_github.json). A dated
#           CRAN snapshot cannot give a commit.
# pak resolves HARD dependencies (dependencies = NA: Depends, Imports and
# LinkingTo, NOT Suggests) against the snapshot. The snapshot never changes,
# so the result is deterministic. Suggests are excluded on purpose. A
# chapter that USES a Suggests package loaded it, so that package is in the
# footprint and is installed by name. To install ALL Suggests would add
# soft dependencies for development (testthat, covr, ...). Their version
# constraints conflict when pak installs on top of common. No closure is
# computed in advance. Each list holds only the packages that the chapters
# loaded, and pak adds their hard dependencies.
#
# Usage: Rscript pak_install_subset.R <packages_cran.txt> [packages_github.json]

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1 || length(args) > 2) {
  stop(
    "usage: Rscript pak_install_subset.R <packages_cran.txt> [packages_github.json]"
  )
}
cran_file <- args[[1]]
gh_file <- if (length(args) == 2) args[[2]] else NULL

cran_names <- readLines(cran_file)
cran_names <- unique(cran_names[nzchar(trimws(cran_names))])

gh_refs <- character(0)
if (!is.null(gh_file)) {
  pins <- jsonlite::fromJSON(gh_file, simplifyVector = FALSE)$GitHubPins
  gh_refs <- vapply(
    names(pins),
    function(n) {
      p <- pins[[n]]
      sprintf("github::%s/%s@%s", p$RemoteUsername, p$RemoteRepo, p$RemoteSha)
    },
    character(1)
  )
}

# --- Repos: CRAN comes from rbase. Bioconductor is the release paired with R.
cran_repo <- getOption("repos")[["CRAN"]]
stopifnot(
  is.character(cran_repo),
  length(cran_repo) == 1L,
  nzchar(cran_repo),
  !grepl("latest", cran_repo, fixed = TRUE)
)
bioc <- as.character(BiocManager::version())
options(
  repos = c(
    getOption("repos"),
    BioCsoft = sprintf("https://bioconductor.org/packages/%s/bioc", bioc),
    BioCann = sprintf(
      "https://bioconductor.org/packages/%s/data/annotation",
      bioc
    ),
    BioCexp = sprintf(
      "https://bioconductor.org/packages/%s/data/experiment",
      bioc
    )
  )
)
cat("CRAN snapshot:", cran_repo, "| Bioconductor:", bioc, "\n")

refs <- c(unname(gh_refs), cran_names)
cat(sprintf(
  "Installing %d main packages (%d CRAN/Bioc by name, %d GitHub-pinned) + their dependencies via pak\n",
  length(refs),
  length(cran_names),
  length(gh_refs)
))

for (attempt in 1:2) {
  ok <- tryCatch(
    {
      pak::pkg_install(refs, dependencies = NA, ask = FALSE)
      TRUE
    },
    error = function(e) {
      message("pak install attempt ", attempt, " failed: ", conditionMessage(e))
      FALSE
    }
  )
  if (isTRUE(ok)) {
    break
  }
  if (attempt == 2L) {
    quit(status = 1L)
  }
  Sys.sleep(20)
}
cat("pak install complete.\n")
