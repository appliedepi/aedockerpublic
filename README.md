# aedockerpublic

The image factory for Applied Epi products. It builds and publishes the Docker images that render
the [epiRhandbook](https://github.com/appliedepi/epirhandbook), and it owns the scripts that
assemble the book from them.

## What this repository is

### Purpose

The live product line is **2.9**: nine images, published to `ghcr.io/appliedepi/aedockerpublic`.
Each image is a package environment. Chapter content is never baked into one: the `.qmd` is
mounted at render time.

The content lives in a separate repository,
[`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook). It owns the `.qmd` files
in every language, and a manifest (`docker-images.yml`) that says which image renders which
chapter. This repository owns packages, images and the render scripts. Neither repository fetches
from the other at build time.

Everything the 2.9 line builds from sits in `epirhandbook/2.9/`. Its own
[README](epirhandbook/2.9/README.md) covers how packages install, how one chapter renders, and how
the book is assembled. [`PROJECT.md`](PROJECT.md) is the design record.

2.5, 2.6, 2.7 and 2.8 are frozen under [`archive/`](archive/README.md). CI never builds them.

### The catalogue

Two files, read together as one catalogue: `images.yaml` at the repository root holds `rbase`, and
`epirhandbook/2.9/images.yaml` holds the other eight images. Base edges cross the two files:
`epirhandbook-common` is FROM `rbase`. Both files are hand-maintained, and `images.yaml`'s own
header comment carries the authoritative field rules.

Each record names the image (`name`), the tags to publish (`tags`), and the image in this
catalogue it is FROM (`base`, or `null`). The `base` edge drives the cascade. Four fields need
more than their name:

| Field | Meaning |
|---|---|
| `dir` | This image's own files: where its Dockerfile lives, and its change-detection scope. |
| `context` | The `docker build` context, when it differs from `dir`. A group's Dockerfile sits in `groups/<group>/` but COPYs shared files from `epirhandbook/2.9/`, so the context is the shared root while change detection stays per group. |
| `renders` | The `.qmd` files this image renders, relative to the handbook source root. A list, for a group image. Required for any image whose `dir` has a `groups` path segment. |
| `live` | `true` means a rebuild of `base` cascades to this image. `false` opts out of that automatic cascade only. A direct edit to the image's own `dir` still builds it. |

The validator ties a group's `renders` list to the group that `dir` and `name` identify, and
refuses a `.qmd` claimed by two images. A record cannot drift into describing another group, and a
chapter cannot be rendered twice.

### Trigger and change detection

**Push to `main` only.** There is no nightly build and no scheduled run.

`.github/scripts/changed_images.py` decides what to rebuild. For each catalogue image it reads the
`org.opencontainers.image.revision` OCI label of the **currently published** image. That is a
metadata-only `docker buildx imagetools inspect`, never a `docker pull`. It then diffs, since that
commit: the image's own `dir`, the shared build-context inputs, and the CI machinery
(`.github/scripts/`, `.github/workflows/`). Anything changed means rebuild. Never published, or no
readable label, also means rebuild, which is fail-closed.

Know this before you push:

- The diff runs from each image's published revision to the pushed commit. Several commits in one
  push produce **one** build of the final state.
- **A change anywhere under `.github/scripts/` or `.github/workflows/` rebuilds all nine images**,
  because it lands in every image's own diff. That includes editing a *test*: `test_plan.py` lives
  under `.github/scripts/`. Batch CI changes rather than pushing them one at a time.
- **Resume is automatic.** After a partial publish, rerun. The images that published carry the
  current commit in their label and are skipped. The ones that failed are rebuilt.

### How dependencies resolve

One source of truth per axis, and **no package version is asserted anywhere**.

- **CRAN**: a dated [Posit Package Manager](https://packagemanager.posit.co) snapshot. The date
  lives in exactly one place, the `rbase` image **tag**. `build_image.sh` matches a trailing
  `-YYYY-MM-DD` on the first tag and passes it as `--build-arg CRAN_SNAPSHOT_DATE`. The rule is
  generic: a tag without a date suffix, such as a group's `2.9`, does not match, and no build
  argument is passed.
- **Bioconductor**: the release paired with R, from `BiocManager::version()`. Derived, never
  stored.
- **GitHub**: the one thing a dated CRAN snapshot cannot pin.
  `epirhandbook/2.9/packages_github.json` holds 6 packages with a commit SHA each.
- **Resolution**: `pak_install_subset.R` runs `pak::pkg_install(refs, dependencies = NA)`. That is
  hard dependencies only (Depends, Imports, LinkingTo), with **Suggests deliberately excluded**.
  There is no hand-computed dependency closure. pak resolves the tree against a snapshot that
  never moves, so the result is deterministic.

`epirhandbook/2.9/README.md` covers what each image installs and why every group image is a
superset of its chapters' package footprints.

### Routine changes

**Add a package to a chapter.** Add the bare name, one per line, to that chapter's
`packages_cran.txt`. Run `python3 epirhandbook/2.9/generate_groups.py`. Commit both files and
push. The chapter's group image and the monolith rebuild.

**Add a chapter.**

1. Capture its package list. Render the chapter once with a knitr `document` hook that writes
   `sort(loadedNamespaces())`. Drop the base R packages: `base`, `compiler`, `datasets`,
   `grDevices`, `graphics`, `grid`, `methods`, `stats`, `tools`, `utils`. Use one name per line,
   with no comments and no blank lines. Save it as
   `epirhandbook/2.9/chapters/<stem>/packages_cran.txt`.
2. Add `<stem>` to a group in `epirhandbook/2.9/groups.yaml`.
3. Add `content/en/<stem>.qmd` to that group's `renders` list in `epirhandbook/2.9/images.yaml`.
   That file is a shared build input, so an edit to it rebuilds all eight 2.9 images.
4. Run `python3 epirhandbook/2.9/generate_groups.py` and commit everything. Push, then watch all
   eight publish: `epirhandbook-common`, the six group images and the monolith.
5. In the handbook repository, add the chapter to every language's `content/<lang>/_quarto.yaml`,
   and add its row to `docker-images.yml`, naming the group image. `build_all_chapters.sh` fails
   a book whose chapter has no manifest row, and a language whose chapter list differs from the
   main language's.

`gis`, restored on 2026-09-02, is the worked example of steps 1 to 4.

**Update the R version or the CRAN snapshot.** Change the date in rbase's tag in `images.yaml`
(`rbase:4.6.0-<YYYY-MM-DD>`). **Never write a date anywhere else.** The tag is the single source of
truth, and the build derives the snapshot URL from it. This rebuilds `rbase` and cascades to
everything.

**Pin a GitHub package to a new commit.** Edit its `RemoteSha` in
`epirhandbook/2.9/packages_github.json`. This rebuilds `epirhandbook-common`, the six group
images and the monolith.

### Visibility

**All nine packages are public.** Verified on 2026-09-08: the GitHub packages API reports
`visibility: public` for each, and reports no private container package in the `appliedepi`
organization. Nothing that consumes these images needs `docker login ghcr.io`.

**Making a GHCR package public cannot be automated.** There is no REST endpoint and no GraphQL
mutation for package visibility. It is done one package at a time in the web UI. Go to the
package page, then the gear icon, then Danger Zone, then Change visibility, then Public. Confirm
by typing the package name. In the `appliedepi` organization this needs an **org admin**. Making
a package public is **irreversible**.

So a **new image name** starts private the first time CI publishes it, and stays private until an
admin does the step above. Adding a chapter to an existing group creates no new image, so it needs
no visibility change. Adding a new group does.

The names of those nine packages are exactly the nine names of the catalogue, which 2.9 keeps
unchanged from 2.8. Every tag published up to 2026-09-08 is `2.8`, apart from
`4.6.0-2026-07-01` on `rbase` and one survivor:
`epirhandbook-common:2.7`, a distinct digest inside the `epirhandbook-common` package, dated
2026-07-24. Nothing builds or consumes that tag. [`archive/README.md`](archive/README.md) has the
detail.

### Known limitations

- **apt packages are not individually version-pinned.** The `ubuntu` base is digest-pinned.
  Packages installed on top of it are not. Accepted.
- **Rendered figures are not byte-reproducible.** Several chapters use unseeded RNG.
- **A pin whose package declares `Remotes:` can drift into a conflict.** Until 2026-09-02
  `epirhandbook-common` pinned babeldown, whose DESCRIPTION declares
  `Remotes: ropensci-review-tools/babelquarto`. pak resolves that to the repository HEAD. Once
  babelquarto's HEAD moved past the pinned babelquarto SHA, the two refs conflicted and
  `epirhandbook-common` could not build (run 33626696019). Neither package was used at render
  time, so both pins were removed, with `tinkr`, which only babeldown needed. `brio`, `fs` and
  `xml2`, which the render scripts import and which those pins had supplied by accident, are now
  explicit in `common/packages_cran.txt`. Before you add a pin, read the package's `Remotes:`
  field. Before you remove one, check what the render scripts import.
- **A base tag moved out of band is not detected.** The build resolves the digest of a non-rebuilt
  base live from whatever its published tag currently points at. That is correct only while the
  registry tag is written by this workflow alone. A manual retag or a force-push would be followed
  silently. This is an accepted trust boundary, not a gap the build checks.

## The images

One section per catalogue image. Every tag, base and chapter stem below comes from the two
catalogue files. A stem is a `renders` entry without the `content/en/` prefix and the `.qmd`
suffix. The six group images follow the parts of the book's navbar.

### rbase

R 4.6.0 on a digest-pinned Ubuntu, with a dated CRAN snapshot and no R packages at all. It carries
the system libraries the packages need, including GDAL, GEOS, PROJ and a JDK for **rJava**. Tag
`4.6.0-2026-07-01`. It is FROM an external base, so it has no base in this catalogue, and it
renders nothing.

### epirhandbook-common

The shared package environment. It holds 59 CRAN and Bioconductor names, all 6 GitHub pins, and
the render scripts on `PATH`. The 59 are the names most chapters share, plus the ones the render
scripts import. Tag `2.9`. Base `rbase`. It renders no chapter, so it declares no `renders` list.

### epirhandbook-basics

The `basics` group, 8 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders `index`,
`editorial_style`, `data_used`, `basics`, `transition_to_r`, `packages_suggested`, `r_projects`
and `importing`.

### epirhandbook-data-management

The `data-management` group, 9 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders `cleaning`,
`dates`, `characters_strings`, `factors`, `pivoting`, `grouping`, `joining_matching`,
`deduplication` and `iteration`.

### epirhandbook-analysis

The `analysis` group, 11 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders
`tables_descriptive`, `stat_tests`, `regression`, `missing_data`, `standardization`,
`moving_average`, `time_series`, `contact_tracing`, `survey_analysis`, `survival_analysis` and
`gis`.

### epirhandbook-data-viz

The `data-viz` group, 11 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders
`tables_presentation`, `ggplot_basics`, `ggplot_tips`, `epicurves`, `age_pyramid`, `heatmaps`,
`diagrams`, `combination_analysis`, `transmission_chains`, `phylogenetic_trees` and
`interactive_plots`.

### epirhandbook-reports

The `reports` group, 4 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders `rmarkdown`,
`reportfactory`, `flexdashboard` and `shiny_basics`.

### epirhandbook-miscellaneous

The `miscellaneous` group, 7 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders
`writing_functions`, `directories`, `collaboration`, `errors`, `help`, `network_drives` and
`data_table`.

### epirhandbook-monolith

Every package of all six groups in one image. Tag `2.9`. Base `epirhandbook-common`. It renders
nothing in CI. It is the dev-container image for contributors, named in the handbook's
`.devcontainer.json`, and it can render any chapter.
