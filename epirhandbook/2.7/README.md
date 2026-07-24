# epiRhandbook 2.7 — per-chapter images on the 2026 stack

2.7 is the epiRhandbook forward-ported to 2026 packages (R 4.6.0), published as one shared
`epirhandbook-common` image plus a thin per-chapter image (49 chapters). Each image is a **package
environment**; the chapter content is rendered at runtime from mounted `.qmd` files, never baked in.

`images.yaml`, the Dockerfiles, and `packages_cran.txt` were originally generated but are now
hand-maintained sources of truth. Edit them directly. The generator that first produced them
(`generate.py`) is archived at `epirhandbook/2.7/archive/` as a record of method, not as a tool to
run again — see `epirhandbook/2.7/archive/README.md`.

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

`build_one_chapter.sh` lives in `common` and is inherited by every chapter image. It renders ONE
chapter, with the `.qmd` passed as an argument:

```bash
docker run --rm -v <book>:/book -w /book \
  epirhandbook-<chapter>:2.7 build_one_chapter.sh chapters/<chapter>.qmd
```

The navbar/sidebar/cross-links come from `_quarto.yml` (part of the mounted book content), so a
single-chapter render already produces a page with correct, complete navigation — **provided**
`_quarto.yml` already matches the language being rendered (see "Assembling the book" below: this is
NOT true by default for a translated chapter, and getting it right is most of what
`build_all_chapters.sh` does).

## Assembling the book

This repo now owns assembly (it used to be a "separate, future concern owned by the epiRhandbook
website repo's CI" — that repo doesn't exist yet, so this repo does it instead). Three scripts,
all installed in `common` alongside `build_one_chapter.sh`:

- **`build_all_chapters.sh`** — the orchestrator. Runs on the CI runner (not in a container): it
  starts one container per chapter render. Reads the language list from `_quarto.yml`
  (`babelquarto.mainlanguage`/`.languages`) and the chapter→image mapping from the handbook repo's
  `docker-images.yml`. For each language, it renders every chapter **twice** in one shared
  workspace, validates the result, then assembles English at the output root and every other
  language under `<lang>/`.
- **`rewrite_lang_config.R`** — rewrites one language's `_quarto.yml` in place (chapter paths,
  title, part titles) before that language's chapters render. Without this, rendering a translated
  `.qmd` against the English `_quarto.yml` fails SILENTLY: exit 0, but the HTML lands outside
  `html_outputs/`, untitled, unnavigable, and duplicating the whole asset tree.
- **`inject_language_links.R`** (+ `inject_language_links.sh` wrapper) — the mandatory post-pass
  that adds the language-switcher dropdown to every emitted page. Quarto never produces this
  itself: a single-language render has no way to know what other languages exist.

**Why every chapter is rendered TWICE:** a chapter rendered before its cross-reference target has
registered in `.quarto/xref` falls back to a same-page anchor that does not exist on that page —
measured directly (`index.fr.html` emitted `href="#download_book_data"` three times, matching no
`id=` anywhere in the page). A second full pass, once every chapter has registered once, resolves
every one of them, reproducing the whole-book reference byte-for-byte. This looks redundant. It is
not — see `build_all_chapters.sh`'s own comments before removing it.

**Why there is no `merge_search.sh`:** the plan for this phase originally included one. It turned
out to be unnecessary. Quarto accumulates the project search index (`search.json`) across separate
`quarto render` invocations on its own, via the `.quarto/` state directory persisted on the shared
mount — three chapters rendered by three separate invocations, in three separate containers,
sharing one mounted project directory, produced ONE `search.json` covering all three pages, and
this held at full scale (49 chapters, 394 search entries, one file). The constraint this replaces
a merge step with: every chapter of one language must render into the SAME workspace, and those
renders must run SEQUENTIALLY — parallel renders within a language would race on writing
`search.json`. Different languages use separate workspaces, so they have no `search.json` to race
on and are independent of each other.

## What is NOT here

- The 2024 frozen images (2.5 monolith, 2.6 split) are superseded; 2.7 is the published deliverable.
- Stale translator prose (5 passages × 9 languages that explain now-deleted code) is a translator
  backlog, not a build blocker. It lives with the content, in the handbook repository:
  [TRANSLATION-BACKLOG.md](https://github.com/appliedepi/epirhandbook/blob/main/TRANSLATION-BACKLOG.md).
- The 2.6 → 2.7 change notes for readers and authors also moved to the handbook repository, and
  are now one cumulative document covering every release:
  [STAKEHOLDERS.md](https://github.com/appliedepi/epirhandbook/blob/main/STAKEHOLDERS.md).
