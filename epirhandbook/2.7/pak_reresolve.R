#!/usr/bin/env Rscript
# Phase 5b discovery installer: a RE-RESOLVE, not a restore.
#
# Takes the 473 package NAMES from epirhandbook/2.5's renv.lock and installs
# each one at whatever version the base image's PINNED CRAN snapshot (and the
# matching Bioconductor release) serves today. The lock's VERSIONS are read
# only to be reported alongside what 2026 resolved to; nothing here installs a
# 2024 version. That is the whole point: Phase 5b asks "does this content still
# work on 2026 packages", so the package set must move and only the names stay
# fixed.
#
# Contrast with epirhandbook/2.5/pak_install.R, which does the opposite: it
# translates every lock entry into an exact pinned ref (pkg@version, an archive
# url::, a github:: SHA) and deliberately keeps pak's solver switched off. Here
# the solver is switched ON and given only names, because re-resolving IS the
# task.
#
# DISCOVERY BUILD: this script NEVER aborts the build on a package failure.
# Some 2024 names no longer exist on CRAN, and recording exactly which ones and
# why is a primary deliverable — a build that died on the first archived
# package would answer nothing. Every failure is recorded with its reason and
# the script exits 0. The real per-package audit is the TSV it writes; there is
# deliberately no "all 473 installed" assertion, unlike the frozen 2.5 image.
#
# Output: /home/handbook/pkg_status.tsv, one row per locked name.

STATUS_TSV <- "/home/handbook/pkg_status.tsv"

# The Bioconductor release paired with R 4.6. Source: bioconductor.org's own
# config.yaml, key `r_ver_for_bioc_ver`, which maps "3.23" -> "4.6". Pinned
# here rather than derived from BiocManager, so the Bioc release this image
# resolves against is a stated decision and not whatever a bootstrap package
# happens to pick.
BIOC_VERSION <- "3.23"

lock <- jsonlite::fromJSON("renv.lock", simplifyVector = FALSE)
pkgs <- lock[["Packages"]]
all_names <- names(pkgs)
cat(sprintf("renv.lock carries %d package names\n", length(all_names)))

# The CRAN repo comes from the base image's Rprofile.site (the pinned PPM
# snapshot). Refuse to run against a floating repo: that would make "which
# versions did the discovery build see" unanswerable.
cran <- getOption("repos")[["CRAN"]]
stopifnot(is.character(cran), length(cran) == 1L, nzchar(cran))
if (grepl("latest", cran, fixed = TRUE)) {
  stop("CRAN repo is floating ('latest'): ", cran)
}
options(
  repos = c(
    CRAN = cran,
    BioCsoft = sprintf(
      "https://bioconductor.org/packages/%s/bioc",
      BIOC_VERSION
    ),
    BioCann = sprintf(
      "https://bioconductor.org/packages/%s/data/annotation",
      BIOC_VERSION
    ),
    BioCexp = sprintf(
      "https://bioconductor.org/packages/%s/data/experiment",
      BIOC_VERSION
    )
  )
)
cat("CRAN snapshot: ", cran, "\n", sep = "")
cat("Bioconductor:  ", BIOC_VERSION, "\n", sep = "")

src <- vapply(all_names, function(n) pkgs[[n]][["Source"]], character(1))
locked_ver <- vapply(
  all_names,
  function(n) pkgs[[n]][["Version"]],
  character(1)
)

# GitHub packages have no snapshot to re-resolve against, so "current" means
# the SAME repo at the SAME ref the lock names — but at that ref's head today,
# not at the lock's frozen SHA. renv records RemoteRef "HEAD" for a default
# branch; pak spells that as a bare user/repo ref.
gh_ref <- function(n) {
  p <- pkgs[[n]]
  r <- p[["RemoteRef"]]
  if (is.null(r) || identical(r, "HEAD")) {
    sprintf("github::%s/%s", p[["RemoteUsername"]], p[["RemoteRepo"]])
  } else {
    sprintf("github::%s/%s@%s", p[["RemoteUsername"]], p[["RemoteRepo"]], r)
  }
}

repo_names <- all_names[src != "GitHub"]
gh_names <- all_names[src == "GitHub"]

ap <- available.packages()
cat(sprintf("available.packages(): %d packages across CRAN + Bioc\n", nrow(ap)))

available <- intersect(repo_names, rownames(ap))
gone <- setdiff(repo_names, rownames(ap))

cat(sprintf(
  "of %d repo-sourced names: %d still published, %d GONE\n",
  length(repo_names),
  length(available),
  length(gone)
))
if (length(gone)) {
  cat("GONE from CRAN/Bioc:\n")
  for (n in gone) {
    cat(sprintf("  %s (locked %s)\n", n, locked_ver[[n]]))
  }
}

# --- failure ledger ---------------------------------------------------------
# An environment, not a named vector or list: `x[["absent"]]` raises
# "subscript out of bounds" on both of those, whereas exists()/get() on an
# environment answer "is there a recorded reason for this name" directly, with
# no partial matching.
reasons <- new.env(parent = emptyenv())
record <- function(n, why) assign(n, why, envir = reasons)
reason_for <- function(n) {
  if (exists(n, envir = reasons, inherits = FALSE)) {
    get(n, envir = reasons)
  } else {
    NULL
  }
}

for (n in gone) {
  record(
    n,
    sprintf(
      "NOT PUBLISHED: absent from the CRAN snapshot and Bioconductor %s (archived or removed from CRAN since 2024)",
      BIOC_VERSION
    )
  )
}

first_line <- function(x) {
  x <- gsub("[\r\t]", " ", x)
  sub("\n.*", "", x)
}

try_install <- function(refs) {
  tryCatch(
    {
      pak::pkg_install(refs, ask = FALSE)
      NULL
    },
    error = function(e) conditionMessage(e)
  )
}

# --- install the still-published names, in chunks ---------------------------
# One 460-ref pak call would be fastest, but a single unresolvable package
# aborts the whole call and installs nothing — useless for discovery. Chunks
# bound that blast radius; a chunk that fails twice is re-tried package by
# package so the failure is attributed to a NAME, not to a batch. Every
# resolution happens against the same immutable snapshot, so chunking cannot
# produce inconsistent versions between chunks.
CHUNK <- 40L
chunks <- split(available, ceiling(seq_along(available) / CHUNK))
for (i in seq_along(chunks)) {
  ch <- chunks[[i]]
  cat(sprintf(
    "=== chunk %d/%d: %d packages ===\n",
    i,
    length(chunks),
    length(ch)
  ))
  msg <- try_install(ch)
  if (is.null(msg)) {
    next
  }
  message("chunk ", i, " failed: ", first_line(msg), " -- retrying once")
  msg <- try_install(ch)
  if (is.null(msg)) {
    next
  }
  message("chunk ", i, " failed twice -- isolating package by package")
  for (n in ch) {
    m <- try_install(n)
    if (!is.null(m)) {
      record(n, paste0("INSTALL FAILED: ", first_line(m)))
      message("  FAILED ", n, ": ", first_line(m))
    }
  }
}

# --- install the GitHub-sourced names, one at a time ------------------------
# Individually, because there are only 7 and each is an independent third-party
# repository whose head may have moved anywhere in two years — attributing a
# failure to the right one matters more than the speed of a batch.
for (n in gh_names) {
  ref <- gh_ref(n)
  cat(sprintf("=== github %s -> %s ===\n", n, ref))
  m <- try_install(ref)
  if (!is.null(m)) {
    record(n, sprintf("GITHUB INSTALL FAILED (%s): %s", ref, first_line(m)))
    message("  FAILED ", n, ": ", first_line(m))
  }
}

# --- audit: what is actually on disk, and does it load ----------------------
inst <- rownames(installed.packages())
rows <- lapply(all_names, function(n) {
  on_disk <- n %in% inst
  ver <- if (on_disk) {
    tryCatch(as.character(packageVersion(n)), error = function(e) "NA")
  } else {
    "NA"
  }
  loads <- if (on_disk) {
    isTRUE(tryCatch(requireNamespace(n, quietly = TRUE), error = function(e) {
      FALSE
    }))
  } else {
    FALSE
  }
  why <- if (!is.null(reason_for(n))) {
    reason_for(n)
  } else if (!on_disk) {
    "NOT INSTALLED: no recorded failure (pulled in by no chunk and never resolved)"
  } else if (!loads) {
    "INSTALLED BUT FAILS TO LOAD"
  } else {
    ""
  }
  data.frame(
    name = n,
    source_2024 = src[[n]],
    version_2024 = locked_ver[[n]],
    version_2026 = ver,
    installed = if (on_disk) "yes" else "no",
    loads = if (loads) "yes" else "no",
    reason = why,
    stringsAsFactors = FALSE
  )
})
out <- do.call(rbind, rows)
write.table(out, STATUS_TSV, sep = "\t", quote = FALSE, row.names = FALSE)

ok_mask <- out[["installed"]] == "yes" & out[["loads"]] == "yes"
n_ok <- sum(ok_mask)
n_bad <- nrow(out) - n_ok
cat(sprintf(
  "\nRE-RESOLVE SUMMARY: %d/%d installed and loading, %d failed\n",
  n_ok,
  nrow(out),
  n_bad
))
if (n_bad) {
  cat("FAILURES:\n")
  bad <- out[!ok_mask, ]
  for (i in seq_len(nrow(bad))) {
    cat(sprintf(
      "  %-24s locked %-12s : %s\n",
      bad[["name"]][i],
      bad[["version_2024"]][i],
      bad[["reason"]][i]
    ))
  }
}
cat("wrote ", STATUS_TSV, "\n", sep = "")
