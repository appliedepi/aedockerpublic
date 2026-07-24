# epiRhandbook 2.7 — per-chapter images on the 2026 stack

2.7 is the epiRhandbook forward-ported to 2026 packages (R 4.6.0), published as one shared
`epirhandbook-common` image plus a thin per-chapter image (49 chapters). Each image is a **package
environment**; the chapter content is rendered at runtime from mounted `.qmd` files, never baked in.

This directory is generated. Do not hand-edit `images.yaml`, the Dockerfiles, or `packages_cran.txt`
— change an input and rerun `generate.py`.

## Reproducibility: one source of truth per axis

- **CRAN** — pinned by a **dated Posit Package Manager snapshot**. The date lives in exactly ONE
  place: the `rbase` image TAG in the root `images.yaml` (`rbase:4.6.0-2026-07-01`).
  `build_image.sh` reads the `YYYY-MM-DD` suffix and passes it as `--build-arg CRAN_SNAPSHOT_DATE`;
  `rbase`'s Dockerfile builds the snapshot URL from it. To move versions, move that tag — nothing
  else. No package version is asserted anywhere; a bare package name resolves to whatever the dated
  snapshot serves (immutable, so reproducible).
- **Bioconductor** — the release paired with R (`BiocManager::version()`), derived from the R
  version, not stored.
- **GitHub** — the one thing not recoverable from a dated CRAN snapshot: a commit SHA per package.
  The 8 GitHub packages and their pinned commits are in `packages_github.json`.
- **System (apt) packages** — the `ubuntu:26.04` base is digest-pinned, but apt packages installed
  on top are NOT individually version-pinned. Known, accepted limitation.

## How packages install (footprint-based, pak resolves the rest)

Each image installs only its **main** packages and lets pak resolve the full dependency tree
(`dependencies = NA`) against the immutable snapshot — deterministic because the snapshot never
moves. There is no hand-computed dependency closure.

- `packages_cran.txt` (per image) — the main CRAN/Bioc packages that image loads, by bare name.
- `packages_github.json` — the 8 GitHub pins. `common` installs all 8, so every chapter (FROM
  common) inherits them and a transitively-pulled GitHub package honours its pin instead of
  resolving from CRAN.

## Rendering a chapter

`build_chapter.sh` lives in `common` and is inherited by every chapter image. It renders ONE
chapter, with the `.qmd` passed as an argument:

```bash
docker run --rm -v <book>:/book -w /book \
  epirhandbook-<chapter>:2.7 build_chapter.sh new_pages/<chapter>.qmd
```

The navbar/sidebar/cross-links come from `_quarto.yml` (part of the mounted book content), so a
single-chapter render already produces a page with correct, complete navigation.

## Assembling the book (epirhandbook WEBSITE repo's CI — not this repo)

Turning 49 per-chapter renders into one site is a separate, future concern owned by the
epiRhandbook website repo's GitHub Actions. The contract:

1. Render each chapter with its own image + `build_chapter.sh` into a shared output directory.
   Navigation and chapter-to-chapter links already resolve (shared `_quarto.yml`, relative links).
2. **Merge search:** a single-chapter render's `search.json` indexes only that chapter and
   overwrites any previous one. The assembly step must merge every chapter's `search.json` into one
   global index, or site search finds only the last-rendered chapter.
3. Deep inline cross-references *into another chapter* (`@fig-`/section refs across chapters)
   resolve fully only in a whole-book render; plain `[text](chapter.qmd)` links are fine.

## What is NOT here

- The 2024 frozen images (2.5 monolith, 2.6 split) are superseded; 2.7 is the published deliverable.
- Stale translator prose (5 passages × 9 languages that explain now-deleted code) is disclosed in
  `CHANGES-2.6-to-2.7.md` Part E — a translator backlog, not a build blocker.
