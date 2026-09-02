# aedockerpublic

The image factory for Applied Epi products. It builds and publishes the Docker images that render
the [epiRhandbook](https://github.com/appliedepi/epirhandbook), and it owns the scripts that
assemble the book from them.

The current product line is **2.8**. Published to `ghcr.io/appliedepi/aedockerpublic`:

| Image | What it is |
|---|---|
| `rbase:4.6.0-2026-07-01` | R 4.6.0 on a digest-pinned Ubuntu, with a dated CRAN snapshot. No R packages. Carries the system libraries the packages need, including GDAL, GEOS, PROJ and a JDK for **rJava**. |
| `epirhandbook-common:2.8` | `FROM rbase`. The 59 CRAN/Bioc packages most chapters share or the render scripts import, all 6 GitHub-pinned packages, and the render scripts. |
| `epirhandbook-<group>:2.8` | `FROM common`. One image per part of the book's navbar: `basics` (8 chapters), `data-management` (9), `analysis` (11, `gis` among them), `data-viz` (11), `reports` (4), `miscellaneous` (7). Each installs the union of its chapters' package lists. |
| `epirhandbook-monolith:2.8` | `FROM common`. Every package of all six groups. It renders nothing in CI. It is the dev-container image for contributors, named in the handbook's `.devcontainer.json`. |

9 images in total. **All nine are public.** Verified on 2026-09-02: an anonymous manifest pull of
each returned 200. See [Visibility](#visibility) for what that means for a new image.

2.5, 2.6 and 2.7 are historical. Their directories stay as a record and CI never builds them.
2.7 published 49 per-chapter images. Nothing consumes those any more, and they are not pullable
without a login.

## Hand-maintained, and generated

Edited by hand, and sources of truth:

- `images.yaml` and `epirhandbook/2.8/images.yaml`, the catalog.
- `epirhandbook/2.8/groups.yaml`, which chapter belongs to which group image.
- `epirhandbook/2.8/packages_github.json`, the 6 GitHub-pinned packages.
- Each chapter's `packages_cran.txt`, under `epirhandbook/2.8/chapters/<stem>/`. 50 files;
  `errors` has an empty one because the chapter runs no R.

Generated, and never edited by hand:

- `epirhandbook/2.8/groups/<group>/packages_cran.txt`, one per group.
- `epirhandbook/2.8/monolith/packages_cran.txt`, the union of the six.

`python3 epirhandbook/2.8/generate_groups.py` writes all seven from `groups.yaml` and the chapter
lists. Run it after any change to those inputs and commit its output. `--check` regenerates in
memory and fails on any difference. CI runs `--check` twice: in `checks.yml` on every pull request
and push, and in `build.yml`'s plan job before any image builds. A stale list fails both.

The per-chapter lists were derived once, from an instrumented render that recorded
`loadedNamespaces()` per chapter (48 of them in 2.7, copied into 2.8 unchanged on 2026-09-02; `gis`
in 2.8 the same way). That derivation is finished, and its generator is archived at
`epirhandbook/2.7/archive/` as a record of method. **Do not run it.**

## The catalog

Two files, read together as one logical catalog: `images.yaml` at the repo root (`rbase`) and
`epirhandbook/2.8/images.yaml` (`epirhandbook-common`, the six groups and the monolith). Base
edges cross between them: `epirhandbook-common` is `FROM rbase`.

| Field | Meaning |
|---|---|
| `name` | Published as `ghcr.io/appliedepi/aedockerpublic/<name>:<tag>`. Must be lowercase, a Docker constraint. |
| `dir` | This image's own files: where its Dockerfile lives, and its change-detection scope. |
| `context` | The `docker build` context, when it differs from `dir`. A group's Dockerfile lives in `groups/<group>/` but COPYs shared files from `epirhandbook/2.8/`, so the context is the shared root while change detection stays per group. |
| `tags` | Tags to publish. The first is used for the local `docker build -t`; all are pushed. |
| `base` | `<name>:<tag>` of another image **in this catalog** that this image is FROM, or `null`. This edge drives the cascade. |
| `renders` | The `.qmd` files this image renders, relative to the handbook source root. A list for a group image. Required for any image whose `dir` has a `groups` path segment. The monolith renders nothing, so it lives in `epirhandbook/2.8/monolith/`, beside `groups/`, not inside it. |
| `live` | `true` = a rebuild of `base` cascades to this image. `false` opts out of that automatic cascade only; a direct edit to its own `dir` still builds it. |

The validator ties a group's `renders` list to the group that `dir` and `name` identify, and
refuses a `.qmd` claimed by two images. A row cannot drift into describing another group, and a
chapter cannot be rendered twice.

## Trigger and change detection

**Push to `main` only.** No nightly build, no scheduled run.

`.github/scripts/changed_images.py` decides what to rebuild. For each catalog image it reads that
image's **currently published** `org.opencontainers.image.revision` OCI label, a metadata-only
`docker buildx imagetools inspect`, never a `docker pull`. It then diffs, since that commit: the
image's own `dir`, the shared build-context inputs, and the CI machinery (`.github/scripts/`,
`.github/workflows/`). Anything changed means rebuild. Never published, or no readable label, means
rebuild (fail-closed).

Know this before you push:

- The diff runs from each image's published revision to the pushed commit, so several commits in one push produce **one** build of the final state.
- **A change anywhere under `.github/scripts/` or `.github/workflows/` rebuilds all 9 images**,
  because it lands in every image's own diff. That includes editing a *test*: `test_plan.py` lives
  under `.github/scripts/`. Batch CI changes rather than pushing them one at a time.
- **Resume is automatic.** After a partial publish, rerun: images that published carry the current
  commit in their label and are skipped; the ones that failed are rebuilt.

## How dependencies resolve

One source of truth per axis, and **no package version is asserted anywhere**.

- **CRAN**: a dated [Posit Package Manager](https://packagemanager.posit.co) snapshot. The date
  lives in exactly one place: the `rbase` image **tag**. `build_image.sh` matches a trailing
  `-YYYY-MM-DD` on the first tag and passes it as `--build-arg CRAN_SNAPSHOT_DATE`; rbase's
  Dockerfile builds the snapshot URL from it. The rule is generic: a tag without a date suffix
  (a group's `2.8`) does not match and no build-arg is passed.
- **Bioconductor**: the release paired with R, from `BiocManager::version()`. Derived, never stored.
- **GitHub**: the one thing a dated CRAN snapshot cannot pin. `epirhandbook/2.8/packages_github.json`
  holds 6 packages with a commit SHA each. `common` installs all 6, so every group inherits them
  and a transitively-pulled GitHub package resolves to its pinned commit instead of coming from CRAN.
- **Resolution**: `pak_install_subset.R` runs `pak::pkg_install(refs, dependencies = NA)`: hard
  dependencies only (Depends/Imports/LinkingTo), **Suggests deliberately excluded**. There is no
  hand-computed dependency closure. pak resolves the tree against a snapshot that never moves, so
  the result is deterministic.

`common` carries what most chapters need. Each group image is `FROM common` and installs its
group's full list; pak skips what common already holds, so the image is a superset of every member
chapter's footprint by construction. Every group Dockerfile ends with a build-time invariant: every
package in its `packages_cran.txt` must load, or the build fails.

## Routine changes

**Add a package to a chapter.** Add the bare name, one per line, to that chapter's
`packages_cran.txt`. Run `python3 epirhandbook/2.8/generate_groups.py`. Commit both. Push. The
chapter's group image and the monolith rebuild.

**Add a chapter.**

1. Capture its package list: render the chapter once with a knitr `document` hook that writes
   `sort(loadedNamespaces())`, and drop the base R packages (`base`, `compiler`, `datasets`,
   `grDevices`, `graphics`, `grid`, `methods`, `stats`, `tools`, `utils`). One name per line, no
   comments, no blank lines. Save it as `epirhandbook/2.8/chapters/<stem>/packages_cran.txt`.
2. Add `<stem>` to a group in `epirhandbook/2.8/groups.yaml`.
3. Add `chapters/<stem>.qmd` to that group's `renders` list in `epirhandbook/2.8/images.yaml`.
   That file is a shared build input: editing it rebuilds every 2.8 image, common included.
4. Run `python3 epirhandbook/2.8/generate_groups.py` and commit everything. Push, and watch the
   group image and the monolith publish.
5. In the handbook repository, add the chapter's row to `docker-images.yml`, naming the group
   image. `build_all_chapters.sh` fails a book whose `_quarto.yml` declares a chapter with no row.

`gis`, restored on 2026-09-02, is the worked example of every step.

**Update the R version or the CRAN snapshot.** Change the date in rbase's tag in `images.yaml`
(`rbase:4.6.0-<YYYY-MM-DD>`). **Never write a date anywhere else.** The tag is the single source of
truth; the build derives the snapshot URL from it. This rebuilds rbase and cascades to everything.

**Pin a GitHub package to a new commit.** Edit its `RemoteSha` in
`epirhandbook/2.8/packages_github.json`. Rebuilds `common` and cascades to the six groups and the
monolith.

## How the handbook uses these images

The content lives in a separate repository,
[`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook), which owns the
`.qmd` files in every language and a manifest (`docker-images.yml`) saying which image renders which
chapter. **This repository owns packages, images and the render scripts; that one owns content and
the choice of image.** Neither fetches from the other at build time.

Chapter content is never baked into an image. The image is a package environment; the `.qmd` is
mounted at render time.

The handbook's CI pulls the group images anonymously. A contributor opens the handbook in a dev
container on the monolith, which can render any chapter.

### The render scripts

They live in `epirhandbook/2.8/common/` and are installed onto `PATH` in `epirhandbook-common`, so
every group image inherits them. Defining them once, here, is what stops the two repositories
drifting apart.

| Script | Runs | Does |
|---|---|---|
| `build_one_chapter.sh` | inside a group image | Renders ONE `.qmd`. |
| `rewrite_lang_config.R` | inside a container | Rewrites `_quarto.yml` for one language. |
| `build_all_chapters.sh` | on the CI runner | Orchestrates across images, so it cannot run inside one. CI extracts it: `docker run --rm <common> cat /usr/local/bin/build_all_chapters.sh > build_all.sh` |
| `inject_language_links.R` | inside a container | Adds the language-switcher dropdown to the assembled site. |

### Four rules the build must obey

Each was established by experiment. Breaking any of them produces a broken site in which **every
render still exits zero**, so an exit code is not evidence here.

1. **Rewrite `_quarto.yml` for a language before rendering that language.** Rendering
   `chapter.fr.qmd` against the English config writes the page *outside* `html_outputs/`, titled
   with the bare filename, marked `lang="en"`, with no sidebar and a duplicated asset tree.
2. **Render every chapter twice.** A chapter rendered before its cross-reference target registers in
   `.quarto/xref` emits a dead same-page anchor instead of a link to the other chapter, and is never
   re-rendered. The second pass resolves them.
3. **Renders must be sequential within a language, sharing one directory.** That is what lets Quarto
   accumulate the search index across separate container runs, and it is why there is no
   `merge_search.sh`. Parallel renders would race on `search.json`. Different languages are
   independent and may run in parallel.
4. **Inject the language switcher afterwards.** Rendering never produces it.

Start each language from a pristine copy: `rewrite_lang_config.R` is not idempotent, and it *moves*
rather than copies the English source when a translation is missing. English assembles to the site
root, not to `en/`.

`build_all_chapters.sh` validates its own output rather than trusting exit codes: every expected page
exists, and the search index references each one. It also **reports** dead same-page fragments
without failing on them. The whole-book reference render of the real book contains 106 of its own,
which are pre-existing content bugs, so a gate there would fail every build forever.

### A chapter must render without network access

CI renders inside a container that reaches only the registry. A chapter that fetches something
while it renders, such as map tiles, fails there. The GIS chapter is the precedent: it reads a
saved basemap from the handbook's `data/gis/` and shows, without running, the code that fetched
it. Prove a new chapter the same way before you add it: render it inside
`docker run --network none`.

## Visibility

**The nine 2.8 images are public.** Verified on 2026-09-02 by an anonymous manifest GET of each,
which returned 200. Nothing that consumes them needs `docker login ghcr.io`.

**Making a GHCR package public cannot be automated.** There is no REST endpoint and no GraphQL
mutation for package visibility. It is done one package at a time in the web UI: package page,
gear icon, Danger Zone, Change visibility, Public, confirming by typing the package name. On the
`appliedepi` organization this needs an **org admin**. Making a package public is **irreversible**.

So a **new image name** starts private the first time CI publishes it, and stays private until an
admin does the step above. Adding a chapter to an existing group does not create a new image, so
it needs no visibility change. Adding a new group does.

The 49 per-chapter 2.7 images were never made public. An anonymous pull of one returns 403. Nothing
uses them since 2.8.

## Known limitations

- **apt packages are not individually version-pinned.** The `ubuntu` base is digest-pinned; packages
  installed on top of it are not. Accepted.
- **Rendered figures are not byte-reproducible.** Several chapters use unseeded RNG.
- **A pin whose package declares `Remotes:` can drift into a conflict.** Until 2026-09-02 `common`
  pinned babeldown, whose DESCRIPTION declares `Remotes: ropensci-review-tools/babelquarto`. pak
  resolves that to the repository HEAD, so once babelquarto's HEAD moved past the pinned
  babelquarto SHA the two refs conflicted and `common` could not build (run 33626696019). Neither
  package was used at render time (the render scripts vendor babelquarto's logic; babeldown serves
  only the handbook's by-hand `_translation.R`), so both pins were removed, with `tinkr`, which only
  babeldown needed. `brio`, `fs` and `xml2`, which the render scripts import and which those pins had
  supplied by accident, are now explicit in `common/packages_cran.txt`. Before you add a pin, read the
  package's `Remotes:` field; before you remove one, check what the render scripts import.
- **A base tag moved out of band is not detected.** The build resolves a non-rebuilt base's digest
  live from whatever its published tag currently points at. That is correct only while the registry
  tag is written by this workflow alone; a manual retag or force-push would be followed silently. An
  accepted trust boundary, not a gap the build checks.
