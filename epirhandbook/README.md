# Epi R Handbook images

These images render the [Epi R Handbook](https://github.com/appliedepi/epirhandbook). Each image is a package environment. No image contains chapter content: the build mounts the `.qmd` at render time.

The live line is **2.9**, in [`2.9/`](2.9/). Its [README](2.9/README.md) covers how packages install, how one chapter renders, and how the book is assembled. The [root README](../README.md) covers what every project shares: `rbase`, the catalogue, the build trigger and visibility.

## The two repositories

This repository holds the packages, the images and the render scripts. The handbook repository, [`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook), holds the `.qmd` files in every language and `docker-images.yml`, which says which image renders each chapter. Neither repository fetches from the other at build time.

The handbook's own README, under [How this all works](https://github.com/appliedepi/epirhandbook#how-this-all-works), covers the content side: the manifest, the languages, the dev container, publishing and the steps for a new chapter or language.

## The images

The catalogue is [`2.9/images.yaml`](2.9/images.yaml). A stem below is a `renders` entry without the `content/en/` prefix and the `.qmd` suffix. The six group images follow the parts of the book's navbar.

| Image | Base | Renders |
|---|---|---|
| `epirhandbook-common` | `rbase` | Nothing. The shared package environment: 58 CRAN and Bioconductor names, all 7 GitHub pins, and the render scripts on `PATH`. The 58 names are the packages that most chapters share, plus the packages that the render scripts import. |
| `epirhandbook-basics` | `epirhandbook-common` | 8 chapters: `index`, `editorial_style`, `data_used`, `basics`, `transition_to_r`, `packages_suggested`, `r_projects`, `importing` |
| `epirhandbook-data-management` | `epirhandbook-common` | 9 chapters: `cleaning`, `dates`, `characters_strings`, `factors`, `pivoting`, `grouping`, `joining_matching`, `deduplication`, `iteration` |
| `epirhandbook-analysis` | `epirhandbook-common` | 11 chapters: `tables_descriptive`, `stat_tests`, `regression`, `missing_data`, `standardization`, `moving_average`, `time_series`, `contact_tracing`, `survey_analysis`, `survival_analysis`, `gis` |
| `epirhandbook-data-viz` | `epirhandbook-common` | 11 chapters: `tables_presentation`, `ggplot_basics`, `ggplot_tips`, `epicurves`, `age_pyramid`, `heatmaps`, `diagrams`, `combination_analysis`, `transmission_chains`, `phylogenetic_trees`, `interactive_plots` |
| `epirhandbook-reports` | `epirhandbook-common` | 4 chapters: `rmarkdown`, `reportfactory`, `flexdashboard`, `shiny_basics` |
| `epirhandbook-miscellaneous` | `epirhandbook-common` | 7 chapters: `writing_functions`, `directories`, `collaboration`, `errors`, `help`, `network_drives`, `data_table` |
| `epirhandbook-monolith` | `epirhandbook-common` | Nothing in CI. All packages of the six groups in one image. It is the dev-container image for contributors, named in the handbook's `.devcontainer.json`, and it can render any chapter. |

Every image has the tag `2.9`. On 2026-10-05 the registry also held `2.8` for all eight, and `2.7` for `epirhandbook-common`. Nothing builds or uses `2.7`.

**Each image renders a smoke document before it is pushed.** `build_image.sh` renders `2.9/common/smoke.qmd` with the image's own `build_one_chapter.sh`. The container has no network, and it has the `R_PROFILE_USER` that `build_all_chapters.sh` sets. A pass shows that R, knitr, ggplot2 and Quarto work together in the image. It does not show that the image holds every package its chapters need.

## Routine changes

**Add a package to a chapter.** Add the bare name, one per line, to that chapter's `2.9/groups/<group>/packages_cran_<stem>.txt`. Run `python3 epirhandbook/2.9/generate_groups.py`. The generator rewrites that group's `packages_cran.txt` and `monolith/packages_cran.txt`. Commit all three changed files and push. CI rebuilds the chapter's group image and the monolith.

**Add a chapter.** These are the steps in this repository. The handbook README lists the steps in the handbook repository.

1. Capture its package list. Render the chapter once with a knitr `document` hook that writes `sort(loadedNamespaces())`. Remove the base R packages: `base`, `compiler`, `datasets`, `grDevices`, `graphics`, `grid`, `methods`, `stats`, `tools`, `utils`. Write one name per line, with no comments and no blank lines. Save the list as `2.9/groups/<group>/packages_cran_<stem>.txt`. That location assigns the chapter to the group.
2. Add `content/en/<stem>.qmd` to that group's `renders` list in `2.9/images.yaml`. That file is a shared build input, so a change to it rebuilds all eight 2.9 images.
3. Run `python3 epirhandbook/2.9/generate_groups.py` and commit all changes. Push. Then watch all eight images publish: `epirhandbook-common`, the six group images and the monolith.

`gis`, restored on 2026-09-02, is the worked example.

**Pin a GitHub package to a new commit.** Change its `RemoteSha` in `2.9/packages_github.json`. This rebuilds all eight 2.9 images.

**Add a group.** A new group is a new image name, so it is private when CI first publishes it. An org admin must make it public. See "Visibility" in the root README.

## Known limitations

- **Rendered figures are not byte-reproducible.** Several chapters use unseeded RNG.
- **A pinned package that declares `Remotes:` can cause a conflict later.** Until 2026-09-02, `epirhandbook-common` pinned babeldown. The babeldown DESCRIPTION declares `Remotes: ropensci-review-tools/babelquarto`, and pak resolves that to the repository HEAD. When the babelquarto HEAD moved past the pinned babelquarto SHA, the two refs conflicted. Then `epirhandbook-common` could not build (run 33626696019). The render did not use either package, so we removed both pins, and also `tinkr`, which only babeldown needed. The render scripts imported `brio`, `fs` and `xml2`, which those pins supplied by accident. These three were made explicit in `common/packages_cran.txt`. `brio` was removed on 2026-09-17, because nothing loads it any more. Before you add a pin, read the package's `Remotes:` field. Before you remove a pin, check what the render scripts import.

## Older lines

2.5, 2.6, 2.7 and 2.8 are in git history, and nothing builds them. `git log --diff-filter=D -- archive/` finds the commit that removed them. `git show <sha>^:archive/<path>` reads a file back. [`CHANGELOG.md`](../CHANGELOG.md) records what each line changed.
