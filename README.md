# aedockerpublic

The image factory for Applied Epi products. It builds and publishes the Docker images that render
the [epiRhandbook](https://github.com/appliedepi/epirhandbook), and it owns the scripts that
assemble the book from them.

Published to `ghcr.io/appliedepi/aedockerpublic`:

| Image | What it is |
|---|---|
| `rbase:4.6.0-2026-07-01` | R 4.6.0 on a digest-pinned Ubuntu, with a dated CRAN snapshot. No R packages. |
| `epirhandbook-common:2.7` | `FROM rbase`. The 56 CRAN/Bioc packages most chapters share, plus all 8 GitHub-pinned packages, plus the render scripts. |
| `epirhandbook-<chapter>:2.7` | `FROM common`. One image per chapter, adding only that chapter's extra packages. 49 of them. |

51 images in total.

> **The images are currently PRIVATE.** GHCR packages default to private and no API can change that
> — see [Visibility](#visibility). Anything that pulls them needs `docker login ghcr.io` first.

## Hand-maintained, not generated

`images.yaml`, `epirhandbook/2.7/images.yaml`, each chapter's `packages_cran.txt`, and
`packages_github.json` are **sources of truth, edited by hand**. Nothing regenerates them.

There was once a generator. It derived the package lists from an instrumented render that recorded
`loadedNamespaces()` per chapter. That derivation is finished, and the generator is archived at
`epirhandbook/2.7/archive/` as a record of method. **Do not run it** — it would overwrite hand-made
edits.

## The catalog

Two files, read together as one logical catalog: `images.yaml` at the repo root (`rbase`) and
`epirhandbook/2.7/images.yaml` (`epirhandbook-common` plus the 49 chapters). Base edges may cross
between them.

| Field | Meaning |
|---|---|
| `name` | Published as `ghcr.io/appliedepi/aedockerpublic/<name>:<tag>`. Must be lowercase — a Docker constraint. |
| `dir` | This image's own files: where its Dockerfile lives, and its change-detection scope. |
| `context` | The `docker build` context, when it differs from `dir`. A chapter's Dockerfile lives in `chapters/<ch>/` but COPYs shared files from `epirhandbook/2.7/`, so the context must be the shared root while change detection stays per-chapter. |
| `tags` | Tags to publish. The first is used for the local `docker build -t`; all are pushed. |
| `base` | `<name>:<tag>` of another image **in this catalog** that this image is FROM, or `null`. This edge drives the cascade. |
| `renders` | The `.qmd` this image renders, relative to the handbook source root. Required for any image whose `dir` is under `chapters/`. |
| `live` | `true` = a rebuild of `base` cascades to this image. `false` opts out of that automatic cascade only; a direct edit to its own `dir` still builds it. |

The validator ties `renders`' stem to both `dir`'s basename and `name`, so a row cannot drift into
describing two different chapters, and cannot publish under a name that misrepresents its content.

## Trigger and change detection

**Push to `main` only.** No nightly build, no scheduled run.

`.github/scripts/changed_images.py` decides what to rebuild. For each catalog image it reads that
image's **currently published** `org.opencontainers.image.revision` OCI label — a metadata-only
`docker buildx imagetools inspect`, never a `docker pull` — and diffs, since that commit: the
image's own `dir`, the shared build-context inputs, and the CI machinery (`.github/scripts/`,
`.github/workflows/`). Anything changed ⇒ rebuild. Never published, or no readable label ⇒ rebuild
(fail-closed).

Worth knowing before you push:

- The diff is against `HEAD`, so several commits in one push produce **one** build of the final state.
- **A change anywhere under `.github/scripts/` or `.github/workflows/` rebuilds all 51 images**,
  because it lands in every image's own diff. That includes editing a *test* — `test_plan.py` lives
  under `.github/scripts/`. Batch CI changes rather than pushing them one at a time.
- **Resume is automatic.** After a partial publish, rerun: images that published carry the current
  commit in their label and are skipped; the ones that failed are rebuilt.

## How dependencies resolve

One source of truth per axis, and **no package version is asserted anywhere**.

- **CRAN** — a dated [Posit Package Manager](https://packagemanager.posit.co) snapshot. The date
  lives in exactly one place: the `rbase` image **tag**. `build_image.sh` matches a trailing
  `-YYYY-MM-DD` on the first tag and passes it as `--build-arg CRAN_SNAPSHOT_DATE`; rbase's
  Dockerfile builds the snapshot URL from it. The rule is generic — a tag without a date suffix
  (a chapter's `2.7`) simply does not match and no build-arg is passed.
- **Bioconductor** — the release paired with R, from `BiocManager::version()`. Derived, never stored.
- **GitHub** — the one thing a dated CRAN snapshot cannot pin. `packages_github.json` holds 8
  packages with a commit SHA each. `common` installs all 8, so every chapter inherits them and a
  transitively-pulled GitHub package resolves to its pinned commit instead of coming from CRAN.
- **Resolution** — `pak_install_subset.R` runs `pak::pkg_install(refs, dependencies = NA)`: hard
  dependencies only (Depends/Imports/LinkingTo), **Suggests deliberately excluded**. There is no
  hand-computed dependency closure — pak resolves the tree against a snapshot that never moves, so
  the result is deterministic.

`common` carries what most chapters need; each chapter image is `FROM common` and adds only its own
delta. Every chapter Dockerfile ends with a build-time invariant: every package in its
`packages_cran.txt` must load, or the build fails.

## Routine changes

**Add a package to a chapter** — add the bare name, one per line, to
`epirhandbook/2.7/chapters/<chapter>/packages_cran.txt`. Push. Exactly that one image rebuilds.

**Update the R version or the CRAN snapshot** — change the date in rbase's tag in `images.yaml`
(`rbase:4.6.0-<YYYY-MM-DD>`). **Never write a date anywhere else.** The tag is the single source of
truth; the build derives the snapshot URL from it. This rebuilds rbase and cascades to everything.

**Add a chapter image** — create `epirhandbook/2.7/chapters/<stem>/` with a `Dockerfile` and a
`packages_cran.txt` (copy an existing chapter), then add a row to `epirhandbook/2.7/images.yaml`.
The name must be `epirhandbook-<stem>` lowercased, and `renders` must be `chapters/<stem>.qmd`.

**Pin a GitHub package to a new commit** — edit its `RemoteSha` in
`epirhandbook/2.7/packages_github.json`. Rebuilds `common` and cascades to all 49 chapters.

## How the handbook uses these images

The content lives in a separate repository,
[`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook), which owns the
`.qmd` files in every language and a manifest (`docker-images.yml`) saying which image renders which
chapter. **This repository owns packages, images and the render scripts; that one owns content and
the choice of image.** Neither fetches from the other at build time.

Chapter content is never baked into an image. The image is a package environment; the `.qmd` is
mounted at render time.

### The render scripts

They live in `epirhandbook/2.7/common/` and are installed onto `PATH` in `epirhandbook-common`, so
every chapter image inherits them. Defining them once, here, is what stops the two repositories
drifting apart.

| Script | Runs | Does |
|---|---|---|
| `build_one_chapter.sh` | inside a chapter image | Renders ONE `.qmd`. |
| `rewrite_lang_config.R` | inside a container | Rewrites `_quarto.yml` for one language. |
| `build_all_chapters.sh` | on the CI runner | Orchestrates across images, so it cannot run inside one. CI extracts it: `docker run --rm <common> cat /usr/local/bin/build_all_chapters.sh > build_all.sh` |
| `inject_language_links.R` | inside a container | Adds the language-switcher dropdown to the assembled site. |

### Four rules the build must obey

Each was established by experiment. Breaking any of them produces a broken site in which **every
render still exits zero** — so an exit code is not evidence here.

1. **Rewrite `_quarto.yml` for a language before rendering that language.** Rendering
   `chapter.fr.qmd` against the English config writes the page *outside* `html_outputs/`, titled
   with the bare filename, marked `lang="en"`, with no sidebar and a duplicated asset tree.
2. **Render every chapter twice.** A chapter rendered before its cross-reference target registers in
   `.quarto/xref` emits a dead same-page anchor instead of a link to the other chapter, and is never
   re-rendered. The second pass resolves them.
3. **Renders must be sequential within a language, sharing one directory.** That is what lets Quarto
   accumulate the search index across separate container runs — and it is why there is no
   `merge_search.sh`. Parallel renders would race on `search.json`. Different languages are
   independent and may run in parallel.
4. **Inject the language switcher afterwards.** Rendering never produces it.

Start each language from a pristine copy: `rewrite_lang_config.R` is not idempotent, and it *moves*
rather than copies the English source when a translation is missing. English assembles to the site
root, not to `en/`.

`build_all_chapters.sh` validates its own output rather than trusting exit codes: every expected page
exists, and the search index references each one. It also **reports** dead same-page fragments
without failing on them — the whole-book reference render of the real book contains 106 of its own,
which are pre-existing content bugs, so a gate there would fail every build forever.

## Visibility

**Making a GHCR package public cannot be automated.** There is no REST endpoint and no GraphQL
mutation for package visibility — verified, not assumed. It is done one package at a time in the web
UI: package page → gear icon → Danger Zone → Change visibility → Public, confirming by typing the
package name. On the `appliedepi` organization this needs an **org admin**.

Making a package public is **irreversible**.

Until an admin does this for all 51, the images are private and every consumer needs
`docker login ghcr.io`.

## Known limitations

- **apt packages are not individually version-pinned.** The `ubuntu` base is digest-pinned; packages
  installed on top of it are not. Accepted.
- **Rendered figures are not byte-reproducible** — several chapters use unseeded RNG.
- **A base tag moved out of band is not detected.** The build resolves a non-rebuilt base's digest
  live from whatever its published tag currently points at. That is correct only while the registry
  tag is written by this workflow alone; a manual retag or force-push would be followed silently. An
  accepted trust boundary, not a gap the build checks.
