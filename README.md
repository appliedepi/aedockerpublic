# aedockerpublic

This repository builds and publishes the Docker images that render the [epiRhandbook](https://github.com/appliedepi/epirhandbook) for Applied Epi. It also holds the scripts that assemble the book from those images.

## What this repository is

### Purpose

The live product line is **2.9**. It has nine images, published to `ghcr.io/appliedepi/aedockerpublic`. Each image is a package environment. No image contains chapter content: the build mounts the `.qmd` at render time.

The content lives in a separate repository, [`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook). That repository holds the `.qmd` files in every language. It also holds a manifest, `docker-images.yml`, that says which image renders which chapter. This repository holds the packages, the images and the render scripts. Neither repository fetches from the other at build time.

The 2.9 Dockerfiles, package lists and render scripts are in `epirhandbook/2.9/`. Its own [README](epirhandbook/2.9/README.md) covers how packages install, how one chapter renders, and how the book is assembled. [`CHANGELOG.md`](CHANGELOG.md) is the historical record.

The lines 2.5, 2.6, 2.7 and 2.8 are not in the working tree. They are in git history. `git log --diff-filter=D -- archive/` finds the commit that removed them. `git show <sha>^:archive/<path>` reads any file back.

### The catalogue

The catalogue is two files. `images.yaml` at the repository root holds `rbase`. `epirhandbook/2.9/images.yaml` holds the other eight images. Base edges cross the two files: `epirhandbook-common` is FROM `rbase`. Both files are maintained by hand. The header comment of `images.yaml` holds the authoritative field rules.

Each record has four required fields:

- `name`: the image name.
- `description`: one line about the image. The planner rejects a record without one, because an image with no `description` publishes its base image's description.
- `tags`: the tags to publish.
- `base`: the image in this catalogue that this image is FROM, or `null`. The `base` edge drives the cascade.

These fields need more explanation:

| Field | Meaning |
|---|---|
| `dir` | This image's own files: where its Dockerfile lives, and its change-detection scope. |
| `context` | The `docker build` context, when it differs from `dir`. A group's Dockerfile is in `groups/<group>/` but COPYs shared files from `epirhandbook/2.9/`. So the context is the shared root, and change detection stays per group. |
| `renders` | The `.qmd` files this image renders, relative to the handbook source root. A list, for a group image. Required for any image whose `dir` has a `groups` path segment. |
| `live` | `true` means a rebuild of `base` cascades to this image. `false` stops only that automatic cascade. A direct edit to the image's own `dir` still builds it. |

The validator checks that a group's `renders` list matches the group that `dir` and `name` identify. It also rejects a `.qmd` that two images claim. So a record cannot describe another group, and no chapter renders twice.

### Trigger and change detection

**CI builds on a push to `main`, or on a manual rerun (`workflow_dispatch`) from `main`.** There is no nightly build and no scheduled run.

`.github/scripts/changed_images.py` decides what to rebuild. For each catalogue image, it reads the `org.opencontainers.image.revision` OCI label of the **currently published** image. It reads the label with `docker buildx imagetools inspect`, which reads metadata only and does not run `docker pull`. Then it diffs these paths from that commit to the pushed commit:

- the image's own `dir`
- the shared build-context inputs
- the CI scripts and workflows, `.github/scripts/` and `.github/workflows/`

A change in any of them means rebuild. An image that was never published, or that has no readable label, also gets a rebuild. The check fails closed.

An image with a `base` gets a second check. `build_image.sh` adds the `org.opencontainers.image.base.digest` label to it. That label is the digest of the base image it was built FROM. `changed_images.py` compares that label with the digest that the base's tag points to now. A missing label, an unreadable base digest or a different digest means rebuild. An image with `live: false` skips this check, because a moved base is the cascade it opts out of.

**Each image renders a smoke document before CI pushes it.** After `docker build`, in both modes, `build_image.sh` renders `epirhandbook/2.9/common/smoke.qmd` with the image's own `build_one_chapter.sh`. The container has no network, and it has the `R_PROFILE_USER` that `build_all_chapters.sh` sets. A failed render stops the script before any push, and verify mode exits 1. An image without `/usr/local/bin/build_one_chapter.sh` gets no render, and the log names it. Today only `rbase` has no render. A pass shows that R, knitr, ggplot2 and Quarto work together in the image. It does not show that the image holds every package its chapters need.

Know these points before you push:

- The diff runs from each image's published revision to the pushed commit. A push of several commits produces **one** build of the final state.
- **A change anywhere under `.github/scripts/` or `.github/workflows/` rebuilds all nine images**, because the change is in every image's own diff. This includes a change to a *test*, because `test_plan.py` is under `.github/scripts/`. Push CI changes together in one push, not one at a time.
- **Resume is automatic.** After a partial publish, run the workflow again. CI skips the images that published. It rebuilds an image that failed, because its own diff shows the change, or its base digest label names the old base. The revision label alone cannot show the second case: a change under the base's `dir` is not in the dependent image's own diff.
- **The base check compares digests, not commits.** A base rebuilt from the same commit still gets a new digest, because its `created` label changes. If a live image FROM that base did not rebuild in the same run, it rebuilds on the next run.

### How dependencies resolve

Each source of packages has one source of truth. **No file pins an R package version.**

- **CRAN**: a dated [Posit Package Manager](https://packagemanager.posit.co) snapshot. The date is in one place only, the `rbase` image **tag**. `build_image.sh` matches a trailing `-YYYY-MM-DD` on the first tag and passes it as `--build-arg CRAN_SNAPSHOT_DATE`. The rule applies to every image. A tag without a date suffix, such as a group's `2.9`, does not match, and the script passes no build argument.
- **Bioconductor**: the release that pairs with R, from `BiocManager::version()`. The build derives it and no file stores it.
- **GitHub**: a dated CRAN snapshot cannot pin these packages. `epirhandbook/2.9/packages_github.json` holds 7 packages, each with a commit SHA.
- **Resolution**: `pak_install_subset.R` runs `pak::pkg_install(refs, dependencies = NA)`. This installs hard dependencies only (Depends, Imports, LinkingTo), and **excludes Suggests**. There is no hand-computed dependency closure. pak resolves the tree against a snapshot that does not change, so the result is deterministic.

`epirhandbook/2.9/README.md` covers what each image installs. It also explains why every group image is a superset of the package footprints of its chapters.

### Routine changes

**Add a package to a chapter.** Add the bare name, one per line, to that chapter's `packages_cran_<stem>.txt`. Run `python3 epirhandbook/2.9/generate_groups.py`. The generator rewrites that group's `packages_cran.txt` and `monolith/packages_cran.txt`. Commit all three changed files and push. CI rebuilds the chapter's group image and the monolith.

**Add a chapter.**

1. Capture its package list. Render the chapter once with a knitr `document` hook that writes `sort(loadedNamespaces())`. Remove the base R packages: `base`, `compiler`, `datasets`, `grDevices`, `graphics`, `grid`, `methods`, `stats`, `tools`, `utils`. Write one name per line, with no comments and no blank lines. Save the list as `epirhandbook/2.9/groups/<group>/packages_cran_<stem>.txt`. That location assigns the chapter to the group.
2. Add `content/en/<stem>.qmd` to that group's `renders` list in `epirhandbook/2.9/images.yaml`. That file is a shared build input, so a change to it rebuilds all eight 2.9 images.
3. Run `python3 epirhandbook/2.9/generate_groups.py` and commit all changes. Push. Then watch all eight images publish: `epirhandbook-common`, the six group images and the monolith.
4. In the handbook repository, add the chapter to `content/<lang>/_quarto.yaml` for every language. Add its row to `docker-images.yml`, with the group image name. `build_all_chapters.sh` fails a book that has a chapter with no manifest row. It also fails a language whose chapter list differs from the main language's.

`gis`, restored on 2026-09-02, is the worked example of steps 1 to 3.

**Update the R version or the CRAN snapshot.** Change the date in the rbase tag in `images.yaml` (`rbase:4.6.0-<YYYY-MM-DD>`). **Do not write the date anywhere else.** The tag is the single source of truth, and the build derives the snapshot URL from it. This change rebuilds `rbase` and cascades to all images.

**The rbase tag is mutable.** Each rbase rebuild overwrites it in the registry, and it has been overwritten at least eight times. The date names the CRAN snapshot that the image was built against. It does not mean that the image bytes are frozen. Reviewers can read "date-pinned" as "immutable" and report a supply-chain defect. This was reported once, as box F27 of appliedepi/epirhandbook#455, and declined. For byte-immutability in a particular build, pin the digest at the point of use.

**Pin a GitHub package to a new commit.** Change its `RemoteSha` in `epirhandbook/2.9/packages_github.json`. This rebuilds `epirhandbook-common`, the six group images and the monolith.

### Visibility

**All nine packages are public.** We verified this on 2026-10-05. The GitHub packages API reports `visibility: public` for each package. It reports no private container package in the `appliedepi` organization. A consumer of these images does not need `docker login ghcr.io`.

**You cannot automate a change of GHCR package visibility to public.** There is no REST endpoint and no GraphQL mutation for package visibility. Change it in the web UI, one package at a time:

1. Open the package page.
2. Select the gear icon.
3. Go to Danger Zone, then Change visibility, then Public.
4. Type the package name to confirm.

In the `appliedepi` organization, this step needs an **org admin**. You **cannot reverse** it.

A **new image name** is private when CI first publishes it. It stays private until an admin does the steps above. A new chapter in an existing group creates no new image, so it needs no visibility change. A new group needs one.

The names of the nine packages are the nine names in the catalogue. 2.9 uses the same names as 2.8. On 2026-10-05 the registry held these tags:

- `rbase`: `4.6.0-2026-07-01`.
- The other eight packages: `2.9` and `2.8`.
- `epirhandbook-common` also holds `2.7`, dated 2026-07-24. Nothing builds or uses that tag.

### Known limitations

- **apt packages do not have individual version pins.** The `ubuntu` base has a digest pin. The packages installed on top of it do not. This is accepted.
- **Rendered figures are not byte-reproducible.** Several chapters use unseeded RNG.
- **A pinned package that declares `Remotes:` can cause a conflict later.** Until 2026-09-02, `epirhandbook-common` pinned babeldown. The babeldown DESCRIPTION declares `Remotes: ropensci-review-tools/babelquarto`, and pak resolves that to the repository HEAD. When the babelquarto HEAD moved past the pinned babelquarto SHA, the two refs conflicted. Then `epirhandbook-common` could not build (run 33626696019). The render did not use either package, so we removed both pins, and also `tinkr`, which only babeldown needed. The render scripts import `brio`, `fs` and `xml2`, which those pins supplied by accident. These three are now explicit in `common/packages_cran.txt`. Before you add a pin, read the package's `Remotes:` field. Before you remove a pin, check what the render scripts import.
- **The build follows a base tag that moved outside CI, and does not check it.** For a base that did not rebuild, the build reads the digest that its published tag points to now. A manual retag or a force-push moves that digest. Every live image FROM that base then rebuilds on the next run, FROM the moved tag. Nothing checks the moved base itself. This is an accepted trust boundary.

## The images

This section has one entry per catalogue image. Every tag, base and chapter stem below comes from the two catalogue files. A stem is a `renders` entry without the `content/en/` prefix and the `.qmd` suffix. The six group images follow the parts of the book's navbar.

### rbase

R 4.6.0 on a digest-pinned Ubuntu, with a dated CRAN snapshot and no R packages. It holds the system libraries that the packages need, including GDAL, GEOS, PROJ and a JDK for **rJava**. Tag `4.6.0-2026-07-01`. It is FROM an external image, so it has no base in this catalogue. It renders nothing.

### epirhandbook-common

The shared package environment. It holds 58 CRAN and Bioconductor names, all 7 GitHub pins, and the render scripts on `PATH`. The 58 names are the packages that most chapters share, plus the packages that the render scripts import. Tag `2.9`. Base `rbase`. It renders no chapter, so it has no `renders` list.

### epirhandbook-basics

The `basics` group, 8 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders `index`, `editorial_style`, `data_used`, `basics`, `transition_to_r`, `packages_suggested`, `r_projects` and `importing`.

### epirhandbook-data-management

The `data-management` group, 9 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders `cleaning`, `dates`, `characters_strings`, `factors`, `pivoting`, `grouping`, `joining_matching`, `deduplication` and `iteration`.

### epirhandbook-analysis

The `analysis` group, 11 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders `tables_descriptive`, `stat_tests`, `regression`, `missing_data`, `standardization`, `moving_average`, `time_series`, `contact_tracing`, `survey_analysis`, `survival_analysis` and `gis`.

### epirhandbook-data-viz

The `data-viz` group, 11 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders `tables_presentation`, `ggplot_basics`, `ggplot_tips`, `epicurves`, `age_pyramid`, `heatmaps`, `diagrams`, `combination_analysis`, `transmission_chains`, `phylogenetic_trees` and `interactive_plots`.

### epirhandbook-reports

The `reports` group, 4 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders `rmarkdown`, `reportfactory`, `flexdashboard` and `shiny_basics`.

### epirhandbook-miscellaneous

The `miscellaneous` group, 7 chapters. Tag `2.9`. Base `epirhandbook-common`. Renders `writing_functions`, `directories`, `collaboration`, `errors`, `help`, `network_drives` and `data_table`.

### epirhandbook-monolith

All packages of the six groups in one image. Tag `2.9`. Base `epirhandbook-common`. It renders nothing in CI. It is the dev-container image for contributors, named in the handbook's `.devcontainer.json`, and it can render any chapter.

---

# Maintaining this repository

This part is for the maintainer of the image lines. A contributor who uses the images does not need it.

### Design decisions, and why

- **`rbase`, not `base`.** The name leaves room for a separate `pythonbase` later. It also matches the existing `ghcr.io/niphr/cs/rbase`.
- **We own all of `rbase`.** It is `FROM ubuntu` (digest-pinned) plus R from **Posit r-builds**, with **no rocker**. We chose control and consistency over lower maintenance.
- **The image installs the openblas-pthread BLAS on purpose.** It is the BLAS that rocker links, so leaving rocker changed no computed numbers. A different BLAS would change values in many chapters.
- **`GITHUB_PAT` is a BuildKit secret.** Do not use `--build-arg` with `ENV`. That puts the token into the image's `Config.Env`, and `docker inspect` or a push exposes it.

### Traps already found

Use these findings. Do not derive them again.

- **pak leaves about 4 GB of build scratch in `/tmp`.** Delete it in the *same* `RUN` layer. If you do not, the image doubles in size (9.5 GB against 5.1 GB).
- **Docker tag races.** When two builds tag the same image name, the last to finish wins, so a bad build can overwrite a good one. Run builds that share a tag one after the other.

### How we work on this

- **Build on compute.** bench has no Docker. Rsync the build context to `compute:~/ae/ehb_build`, then run `docker build` over SSH.
- **Check the built image, not only the Dockerfile.** After every build, run `docker inspect <img> --format '{{.Config.Env}}'` to confirm that the image holds no token. A review of the source alone, codex included, does not find a secret in the image.
