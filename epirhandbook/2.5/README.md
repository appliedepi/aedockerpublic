# epirhandbook:2.5 — reproducible build environment (Phase 1: stabilize)

A time-capsule Docker image that reconstructs the toolchain the Applied Epi
**epiRhandbook** (v2.5) was pinned to, so its content compiles and renders again
after years of drift. Built **from `renv.lock`**, exactly as the handbook's own CI did.

- Image: `epirhandbook:2.5-p1` (~5.0 GB)
- Content baseline: `epiRhandbook_eng` branch `deploy-preview` (the live v2.5), worked on
  locally as branch `stabilize-v2.5`. (NB: `master` HEAD is "v2.5 reverted"; the graphical
  edits on branch `richard` are a *later* phase, saved separately at commit `ebc8b27`.)

## Reconstructed toolchain (all confirmed from the repo itself)
| Component | Value | Source of truth |
|---|---|---|
| R | **4.3.2** | `renv.lock` + `.github/workflows/render_book_on_pr.yml` |
| Bioconductor | **3.18** | `renv.lock` |
| Quarto CLI | **1.4.550** | the CI workflow |
| OS | Ubuntu 22.04 jammy | `FROM rocker/r-ver:4.3.2` |
| Packages | **473**, restored from `renv.lock` | vendored `renv.lock` |
| Render | `quarto render` per chapter (or `quarto_runfile.R` for the full babelquarto/9-lang book) | the CI workflow |

## The reproduction gaps we hit (and fixed) — read this before touching the build
A years-stale build does not "just restore." Every one of these was a real blocker:

1. **Dead package sources.** `renv.lock` sourced `babelquarto`/`tinkr`/`xslt` from r-universe,
   which serves only *current* builds → the pinned dev versions 404. Repinned in the lock
   (commit `d05c52c`): `babelquarto` → GitHub `ropensci-review-tools/babelquarto@71e23a2` (the
   v0.0.0.9000 live at the Jan-2025 build); `tinkr`/`xslt` → CRAN. **Versions unchanged.**
2. **`gh auth token` doesn't exist on the old `gh`.** Get the token from
   `~/.config/gh/hosts.yml` (`oauth_token:`), not `gh auth token`, to pass `GITHUB_PAT` for the
   7 GitHub-SHA-pinned packages.
3. **PPM binaries are a dead end for this lock.** The lock mixes versions from different dates
   (some current on a snapshot, others archived). renv's PPM `__linux__` binary transform breaks
   its *source-archive fallback* for the archived ones, so no single PPM snapshot restores the
   whole lock. **Restore from the lock's own `cloud.r-project.org`** (has every version) — source
   compile, same as the original CI.
4. **The 20-s-per-package stall (the big one).** Most pinned versions are archived, so renv uses
   its CRAN-archive fallback, which probes every repo in `R$Repositories` **in order**. This lock
   lists **CRAN last, after 5 Bioconductor repos** → ~4 s wasted probing each Bioc repo for every
   archived CRAN package (~20 s/pkg → ~2.6 h). Fix: a `jq` step **reorders CRAN first**
   (`19.5 s → 0.27 s` per package; version-neutral, order only).
5. **System libs missing from the CI apt list.** The CI's render used `continue-on-error`, so
   failed compiles didn't block it — `renv::restore` has no such tolerance. Added: **`libgsl-dev`**
   (SemiCompRisks) and **`cmake`** (nloptr's bundled NLopt).
6. **`MAKEFLAGS=-j12` breaks Fortran-module packages.** Within-package parallel make races on
   undeclared Fortran module deps — `frailtypack` fails "Cannot open module file 'comon.mod'".
   Do **not** set `MAKEFLAGS=-jN`; use cross-package `options(Ncpus=12)` instead (race-free).

Build-cache note: the restore RUN uses a BuildKit `--mount=type=cache,target=/opt/renv/cache`
with `RENV_CONFIG_CACHE_SYMLINKS=FALSE`, so a rebuild after a sysreq fix reuses already-compiled
packages instead of recompiling all 473 (~60 min from scratch, ~10 min cached).

## Where the packages live (important for rendering)
`RENV_PATHS_LIBRARY=/opt/renv/library` in the Dockerfile is effectively a **no-op**: without a
`.Rprofile` to activate the renv project, `renv::restore` installed straight into the default
`/usr/local/lib/R/site-library` (494 pkgs = the 473 locked + rocker's base). That library **is**
the pinned environment and is baked into the image. So to render, **disable renv's autoloader**
so R uses `site-library`:

```bash
docker run --rm -e RENV_CONFIG_AUTOLOADER_ENABLED=FALSE \
  -v <handbook-source>:/book -w /book epirhandbook:2.5-p1 \
  quarto render new_pages/<chapter>.qmd     # or: Rscript -e 'source("quarto_runfile.R")' for the full book
```
Render into a **writable copy** of the source, not the reference — `quarto_runfile.R`'s
`render_book()` deletes `html_outputs/` first.

**Two Linux render-prep steps** (the content was authored on case-insensitive macOS):
1. `python3 fix_image_case.py <source>` — creates case-matching image symlinks. Without it the full
   book render aborts on `index.qmd`'s banner (`banner beige` vs the real `Banner Beige`).
2. Comment out `new_pages/gis.qmd` in the source `_quarto.yml` — `gis` fetches live OSM tiles at
   render time (`OpenStreetMap::openmap()`), which aborts the whole book render; it's the one
   external-dependency chapter (`plot_continuous` is already commented out upstream).

## Build
On a Docker host (bench has no Docker — use `compute`):
```bash
DOCKER_BUILDKIT=1 docker build --secret id=github_pat,src="$HOME/.ghtoken" -t epirhandbook:2.5-p1 .
```

## Verification (Phase 1 result)
- **Build:** all 473 locked packages install and **load** at their exact locked versions
  (incl. the three that fought us: SemiCompRisks/GSL, nloptr/CMake, frailtypack/Fortran). The load
  is a **build-time invariant** — a final Dockerfile step `requireNamespace()`s every locked package
  and fails the build if any does not load.
- **Render + reproduction:** the live-site diff below is the real verification. (An earlier diff
  against the *committed* `html_outputs/` scored only 37/48 ≥0.95 — because that HTML is a stale
  June-2024 render, not the live target. It's a historical baseline, not the reference.)

## The reproduction target — and the result (IMPORTANT)
Stabilization revealed **three conflated time-slices** of the handbook. Don't mix them:
- **June 2024** — the committed `html_outputs/` + this `renv.lock`. A stale historical baseline only.
- **Sep 18 2024** — the **live website** (epirhandbook.com pages are stamped "Last updated Sep 18
  2024"). Its source commit is `c3cbc76` ("Rendering after remove old handbook"); its lockfile is
  **byte-identical to the June lock this image is built from** — so this image *is* the live-site
  environment. (The site is built externally on Netlify — there's no deploy config in the repo —
  which is why the Sep-18 render was published but never committed, leaving `html_outputs/` stale.)
- **Jan 2025** — the current `.qmd` on `deploy-preview`, edited *after* the live render (adds
  gtsummary 2.x `tbl_wide_summary`, etc.) and **never published**.

**The reproduction target is the LIVE site (Sep 2024), NOT the stale committed HTML.** Rendering the
Sep-18 content (`c3cbc76`) on this image and diffing against a fresh crawl of epirhandbook.com:
- **English: 65/67 chapters render; 46/49 crawlable chapters match the live site at ≥0.98
  similarity, median 0.9976** — near-exact reproduction. (Against the *stale June HTML* it was only
  37/48 ≥0.95 — a worse reference, which is the point.)
- **All 8 published languages** (en + fr/es/vn/jp/pt/tr/ru; `de` is staged, not live — 0/48 crawlable)
  render via the full production `render_book()` (`quarto_runfile.R`) and each reproduces the live
  site at **median ~0.99 similarity** (per-language medians 0.984–0.993). The residual ~1% is
  dominated by the sidebar chapter **renumbering from excluding `gis`** (shifts the number on every
  page) plus volatile colophons (`editorial_style` prints `session_info`; `directories` prints
  `fs::dir_info()` mod-dates). `jp`'s slightly lower score is the word-similarity metric
  under-measuring space-less Japanese, not a content gap. The residual is **fully accounted for by
  non-environment factors** — no *sign* of package/environment infidelity in the diff. **Caveat on
  rigor** (per the codex gate): this is **full-page text similarity**, so computed outputs (tables,
  printed values) are *included* in the match but were **not separately extracted and compared**; a
  stronger check — isolating `<main>` computed outputs and normalizing volatile blocks — is the next
  increment (staged in `verify/`). The gis-included per-chapter EN diff above (median 0.9976) is the
  truest content match; the full-book numbers here carry the gis-exclusion sidebar artifact.

The earlier "4 chapters need newer packages" was a **content-era artifact** — rendering the
*Jan-2025* source on the *June* lock. On the Sep-18 content, `tables_descriptive`/`survey_analysis`
render fine.

**Frozen evidence:** the full per-page results (similarity + `sha16` content hashes of both sides) and
the exact re-runnable procedure are in [`verify/`](verify/VERIFICATION.md).

## Two non-environment render failures (not the image's fault)
- `plot_continuous` → `drop_na` "not found": `drop_na` has existed since tidyr 0.6.0 (2016); the
  chapter just doesn't `library(tidyr)`, and it's an **unused `.qmd`** (not in the book/live site).
- `gis` → `osmtile()`: the handbook fetches **live OpenStreetMap tiles at render time** — a flaky
  external network dependency, not a package/env issue.

## Moving forward — Phase 5 (a separate step from reproduction)
Modernization is a **minimal forward-port of THIS frozen content** (the reproduced Sep-18 baseline) to
current (2026) packages: a modern base image + current package versions, changing the source **as little
as possible** — only what actually **breaks** on the new stack (deprecated/removed functions, dropped
packages like `OpenStreetMap` for `gis`, changed APIs).

The success metric is the **size of that source diff** — as few changes as possible — **NOT** output
equivalence. Two years of newer package versions render differently (ggplot2 defaults, table formatting,
…), so the modern output will *not* match the 4.3.2 render, and where an API changed the source *must*
change — that's expected, not a failure. (Output-equivalence against
[`verify/manifest.tsv`](verify/manifest.tsv) is the bar for **Phase 2**'s pak rehearsal, which keeps the
*same* package versions — not for Phase 5.)

The separate **52-chapter Jan-2025 content drift** on `deploy-preview` is **parked** — reviewed only at
the very end to salvage anything useful, not part of the forward-port.
