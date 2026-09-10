#!/usr/bin/env Rscript
# Phase 5b installer: installs an image's MAIN packages and lets pak resolve
# the full dependency tree from the pinned sources. Two inputs, split by how
# each package is pinned:
#
#   packages_cran.txt   -- one package NAME per line. CRAN and Bioconductor
#                          packages, installed by bare name. Required.
#   packages_github.json -- the GitHub packages, each with a commit SHA.
#                          Optional: only `common` carries it (it installs all
#                          the GitHub pins once, so every chapter FROM common
#                          inherits them and a transitive pull honours the pin
#                          rather than resolving the package from CRAN).
#
# ONE SOURCE OF TRUTH, NO HAND-COMPUTED DEPENDENCY GRAPH:
#   CRAN   -- versions come from the dated PPM snapshot, owned by rbase's tag
#             and INHERITED here via getOption("repos"). Not asserted here.
#   Bioc   -- the R-paired release (BiocManager::version()), derived from the R
#             version, so not stored anywhere as a second source.
#   GitHub -- a commit SHA per package (packages_github.json). A commit is the
#             one thing NOT recoverable from a dated CRAN snapshot.
# pak resolves HARD dependencies (dependencies = NA -- Depends/Imports/
# LinkingTo, NOT Suggests) against the immutable snapshot -- deterministic
# because the snapshot never moves. Suggests are deliberately excluded: a
# Suggests package a chapter actually USES is already in its footprint (it
# loaded), so it is installed explicitly; pulling in ALL Suggests instead
# drags in dev-only soft deps (testthat, covr, ...) whose version constraints
# conflict on an incremental install onto common. No pre-computed closure:
# each list holds only the packages actually loaded; pak adds their hard deps.
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

# --- Repos: CRAN inherited from rbase; Bioconductor from the R-paired release
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
