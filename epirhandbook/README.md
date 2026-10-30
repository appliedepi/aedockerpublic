# Epi R Handbook images

These images render the [Epi R Handbook](https://github.com/appliedepi/epirhandbook). Each image is a package environment. No image contains chapter content: the build mounts the `.qmd` at render time.

The live line is the one version directory here. Paths below write it as `<version>/`, and its name is also the tag of every image in it. [`CHANGELOG.md`](../CHANGELOG.md) records each change to it. The [root README](../README.md) covers what every project shares: `rbase`, the catalogue, the build trigger and visibility.

## The two repositories

This repository holds the packages, the images and the render scripts. The handbook repository, [`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook), holds the `.qmd` files in every language, the chapter data and `docker-images.yml`, which says which image renders each chapter. Neither repository fetches from the other at build time.

The handbook's own README, under [How this all works](https://github.com/appliedepi/epirhandbook#how-this-all-works), covers the content side: the manifest, the languages, the dev container, publishing and the steps for a new chapter or language.

## The images

The catalogue is `<version>/images.yaml`. It lists every image, its base and, for a group image, the chapters it renders. Each record's `description` says what the image is for, and the comment above a record says why it has no `renders` when it has none. This README does not repeat the list.

**Each image renders a smoke document before it is pushed.** `build_image.sh` renders `<version>/common/smoke.qmd` with the image's own `build_one_chapter.sh`. The container has no network, and it has the `R_PROFILE_USER` that `build_all_chapters.sh` sets. A pass shows that R, knitr, ggplot2 and Quarto work together in the image. It does not show that the image holds every package its chapters need.

## Routine changes

**Add a package to a chapter.** Add the bare name, one per line, to that chapter's `<version>/groups/<group>/packages_cran_<stem>.txt`. Run `python3 epirhandbook/<version>/generate_groups.py`. The generator rewrites that group's `packages_cran.txt` and `monolith/packages_cran.txt`. Commit all three changed files and push. CI rebuilds the chapter's group image and the monolith.

**Add a chapter.** These are the steps in this repository. The handbook README lists the steps in the handbook repository.

1. Capture its package list. Render the chapter once with a knitr `document` hook that writes `sort(loadedNamespaces())`. Remove the base R packages: `base`, `compiler`, `datasets`, `grDevices`, `graphics`, `grid`, `methods`, `stats`, `tools`, `utils`. Write one name per line, with no comments and no blank lines. Save the list as `<version>/groups/<group>/packages_cran_<stem>.txt`. That location assigns the chapter to the group.
2. Add `content/en/<stem>.qmd` to that group's `renders` list in `<version>/images.yaml`. That file is a shared build input, so a change to it rebuilds every image in it.
3. Run `python3 epirhandbook/<version>/generate_groups.py` and commit all changes. Push. Then watch every image in `<version>/images.yaml` publish.

**Pin a GitHub package to a new commit.** Change its `RemoteSha` in `<version>/packages_github.json`. This rebuilds every image in `<version>/images.yaml`.

**Add a group.** A new group is a new image name. After CI first publishes it, check that it is public. See "Visibility" in the root README.

## How packages install

Every chapter has its own package list, `<version>/groups/<group>/packages_cran_<stem>.txt`, with one bare CRAN or Bioconductor name per line. Every chapter has one. A chapter that runs no R has an empty list.

The list is in the directory of the group image that renders the chapter. That location assigns the chapter to the group, so there is no separate assignment file. The choice of group is an editorial decision: `gis` is in `analysis` because it is in the Analysis part of the book.

[`generate_groups.py`](2.9/generate_groups.py) makes the generated lists from them:

- one `<version>/groups/<group>/packages_cran.txt` per group, which is the union of the full lists of its chapters
- `<version>/monolith/packages_cran.txt`, which is the union of the group lists

A group's generated list is the file with no `_<stem>` in its name. **Do not edit a generated list by hand.** Edit the input and run the generator again:

```bash
python3 epirhandbook/<version>/generate_groups.py           # write the generated lists
python3 epirhandbook/<version>/generate_groups.py --check   # regenerate in memory, fail on a difference
```

Both modes first check the layout against [`images.yaml`](2.9/images.yaml), one group at a time:

- Every chapter in a group image's `renders` list MUST have a package list in that image's own directory.
- Every package list in that directory MUST belong to a chapter that the image renders.

So a chapter in the wrong group fails the check, even when its list is empty and no generated list changes.

CI runs `--check` in two places: in `checks.yml` on every pull request and push, and in the plan job of `build.yml` before any image builds. A stale list fails both.

[`packages_github.json`](2.9/packages_github.json) holds the GitHub-pinned packages, each with a commit SHA. `epirhandbook-common` installs all of them, so every group image inherits them. When a package pulls in one of them as a dependency, pak uses the pinned commit and not the CRAN version.

[`pak_install_subset.R`](2.9/pak_install_subset.R) does every install. It reads a CRAN list, and, for `epirhandbook-common` only, the pin file. Then it runs `pak::pkg_install(refs, dependencies = NA)`. There is no hand-computed dependency closure. No file states a package version: versions come from the dated CRAN snapshot that the `rbase` tag sets. See "How dependencies resolve" in the root README.

A group image is FROM `epirhandbook-common`. It installs the **full** list of its group on top, not only the packages that common does not have. pak skips what common already holds. So the image is always a superset of the package footprint of each of its chapters. Every group Dockerfile ends with a build-time check: every package in its own `packages_cran.txt` MUST load, or the build fails.

The per-chapter lists came from instrumented renders that recorded `loadedNamespaces()` for each chapter. A new chapter's list is captured the same way, as "Add a chapter" describes. The old generator for the lists is in git history. **Do not run it.**

## Rendering one chapter

`<version>/common/build_one_chapter.sh` is installed on `PATH` in `epirhandbook-common`, so every group image inherits it. It renders ONE `.qmd`, given as an argument. The book content is mounted, and the working directory is the chapter's own language project:

```bash
docker run --rm -v <book>:/book -w /book/content/<lang> \
  ghcr.io/appliedepi/aedockerpublic/epirhandbook-<group>:<version> \
  build_one_chapter.sh <stem>.qmd
```

Every language is its own Quarto book project. Its `content/<lang>/_quarto.yaml` holds the language, the title, the chapter list, the navbar and the cross-links. So a single-chapter render produces a page with full navigation, **but only when the render runs inside that project.**

The caller MUST start the render inside the project. The output directory `html_outputs/`, the sidebar and the cross-links are all project-level settings. A render started in a different directory gets none of them. `quarto render` then exits 0 and writes a standalone page next to its source. That page has no book navigation and its own copy of the asset tree. So an exit code of 0 does not prove a correct render.

**A chapter MUST render without network access.** `build_all_chapters.sh` starts every chapter container with `--network none`. A chapter that fetches something during the render, such as map tiles, fails the build. A chapter that installs a missing package during the render also fails, for example with `pacman::p_load()`. Add that package to the chapter's package list instead. The GIS chapter shows how to handle data. It reads a saved basemap from the handbook's `data/gis/`, and it shows the code that fetched the basemap without running it.

**Every chunk warning goes to the build log.** `build_all_chapters.sh` also sets `R_PROFILE_USER=/usr/local/lib/ehb/warnings_to_log.R`. `epirhandbook-common` installs [`common/warnings_to_log.R`](2.9/common/warnings_to_log.R) at that path. Each R warning that a chunk raises writes one line, `EHB-WARNING<TAB><input file><TAB><chunk label><TAB><message>`. This is true when `warning` is true, false or NA, in the chunk or for the whole document. Each error that an `error: true` chunk captures writes an `EHB-ERROR` line. These lines are a report, and they do not fail the build. The header of that file lists the cases it does not cover, such as a chunk from the knitr cache. The profile also reads a `.Rprofile` in the working directory, as R does without `R_PROFILE_USER`.

## Assembling the book

`<version>/common/build_all_chapters.sh` controls the render of the whole book. It runs on the CI runner, not inside a container, because it starts one container for each chapter render. But it is stored in `epirhandbook-common`, so that it has one source of truth. CI extracts it first:

```bash
docker run --rm <common-image> cat /usr/local/bin/build_all_chapters.sh > build_all.sh
```

It reads the language list from the handbook's `languages.yml`: `main`, and a `code` for each entry of `languages`. It reads the mapping from chapter to image from the handbook's `docker-images.yml`. These cases fail the build:

- a book chapter with no manifest row
- a language whose `_quarto.yaml` has a different chapter list from the main language's
- a language whose `_quarto.yaml` has a different chapter order from the main language's

### Four rules the build MUST follow

Experiments found each rule. If the build breaks any of them, the site is broken, but **every render still exits zero**.

1. **Render each chapter from inside its own language project.** See "Rendering one chapter" above for the failure that otherwise occurs.
2. **Render every chapter twice.** A chapter rendered before its cross-reference target registers in `.quarto/xref` gets a dead same-page anchor. Without a second pass, nothing renders it again. The second pass resolves these anchors.
3. **Render one chapter at a time within a language, into one shared directory.** This lets Quarto build the search index across separate container runs. For this reason there is no `merge_search.sh`. Parallel renders would race on `search.json`. Different languages are independent and MAY run in parallel.
4. **Add the language switcher after the render.** The render does not produce it. `<version>/common/inject_language_links.R` adds the dropdown in a separate pass over the assembled site.

Each language renders in its own copy of the checkout. That copy excludes any `html_outputs/`, `.quarto/` and `*_files/` that the source already holds. So a stale local render cannot pass the validation below when no container has started.

Every language assembles to its own `<lang>/` directory, the main language included. The site root holds only `images/` and a four-line redirect stub to the main language.

`build_all_chapters.sh` validates its own output and does not rely on exit codes. It checks that every expected page exists, and that the search index refers to each page. It **fails** on a dead same-page fragment: an `href="#x"` with no `id="x"` on the same page. It names each one as `<page>#<fragment>`. It also fails when it cannot count them. A handbook with such a bug fails here until it is fixed.

[`common/test_fixture/`](2.9/common/test_fixture/) is a two-chapter handbook that the script accepts. Its README lists the variants that test the network rule, the warning log and the fragment check.

`--only-lang <code>` renders one language, for one leg of a CI matrix. The site of that language goes to the root of the output directory, with no `<lang>/` directory, no `images/` copy and no stub. It needs `--no-inject`, and does not run without it. The switcher works on the assembled site, so it runs once, after the legs are joined.

## Known limitations

- **Rendered figures are not byte-reproducible.** Several chapters use unseeded RNG.
- **A pinned package that declares `Remotes:` can cause a conflict later.** pak resolves a `Remotes:` entry to that repository's HEAD. When HEAD moves past another pin of the same package, the two refs conflict and `epirhandbook-common` cannot build. Before you add a pin, read the package's `Remotes:` field. Before you remove a pin, check what the render scripts import, because a pin can supply a package they need by accident. [`CHANGELOG.md`](../CHANGELOG.md) records the babeldown case.

## Older lines

Older lines are not in the working tree. They are in git history, and nothing builds them. `git log --diff-filter=D --name-only -- <path>` finds the commit that removed a path, and `git show <sha>^:<path>` reads a file back. [`CHANGELOG.md`](../CHANGELOG.md) records what each line changed.
