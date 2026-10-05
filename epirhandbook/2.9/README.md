# epiRhandbook 2.9: the group images

2.9 publishes one shared `epirhandbook-common` image, six group images and a monolith, all on the 2026 package stack (R 4.6.0). Each image is a package environment. The images do not contain chapter content. They render it at runtime from mounted `.qmd` files.

2.9 has the same nine images and the same package lists as 2.8. The difference is the handbook layout that the render scripts use: every language is now its own Quarto book project, at `content/<lang>/`. 2.8 is in git history, not in the working tree.

This file covers how this directory works. The [project README](../README.md) covers the images, routine changes and the handbook repository. The [root README](../../README.md) covers what every project shares: `rbase`, the catalogue and the build trigger.

## How packages install

Every chapter has its own package list, `groups/<group>/packages_cran_<stem>.txt`, with one bare CRAN or Bioconductor name per line. There are 50 of these lists, one per chapter. `groups/miscellaneous/packages_cran_errors.txt` is empty, because that chapter runs no R.

The list is in the directory of the group image that renders the chapter. That location assigns the chapter to the group, so there is no separate assignment file. The choice of group is an editorial decision: `gis` is in `analysis` because it is in the Analysis part of the book.

[`generate_groups.py`](generate_groups.py) makes seven lists from those 50:

- one `groups/<group>/packages_cran.txt` per group, which is the union of the full lists of its chapters
- `monolith/packages_cran.txt`, which is the union of the six group lists

A group's generated list is the file with no `_<stem>` in its name. **Do not edit a generated list by hand.** Edit the input and run the generator again:

```bash
python3 epirhandbook/2.9/generate_groups.py           # write the seven lists
python3 epirhandbook/2.9/generate_groups.py --check   # regenerate in memory, fail on a difference
```

Both modes first check the layout against [`images.yaml`](images.yaml), one group at a time:

- Every chapter in a group image's `renders` list MUST have a package list in that image's own directory.
- Every package list in that directory MUST belong to a chapter that the image renders.

So a chapter in the wrong group fails the check, even when its list is empty and no generated list changes.

CI runs `--check` in two places: in `checks.yml` on every pull request and push, and in the plan job of `build.yml` before any image builds. A stale list fails both.

[`packages_github.json`](packages_github.json) holds the 7 GitHub-pinned packages, each with a commit SHA. `epirhandbook-common` installs all 7, so every group image inherits them. When a package pulls in one of them as a dependency, pak uses the pinned commit and not the CRAN version.

[`pak_install_subset.R`](pak_install_subset.R) does every install. It reads a CRAN list, and, for `epirhandbook-common` only, the pin file. Then it runs `pak::pkg_install(refs, dependencies = NA)`. There is no hand-computed dependency closure.

A group image is FROM `epirhandbook-common`. It installs the **full** list of its group on top, not only the packages that common does not have. pak skips what common already holds. So the image is always a superset of the package footprint of each of its chapters. Every group Dockerfile ends with a build-time check: every package in its own `packages_cran.txt` MUST load, or the build fails.

The per-chapter lists came from one instrumented render that recorded `loadedNamespaces()` for each chapter. 48 lists were captured for 2.7 and copied here unchanged on 2026-09-02. `gis` was captured the same way in 2.8. The `errors` chapter needed no capture, which makes 50. This derivation is complete. Its generator was removed with the rest of the archived lines, and you can read it in git history. **Do not run it.**

## Rendering one chapter

`common/build_one_chapter.sh` is installed on `PATH` in `epirhandbook-common`, so every group image inherits it. It renders ONE `.qmd`, given as an argument. The book content is mounted, and the working directory is the chapter's own language project:

```bash
docker run --rm -v <book>:/book -w /book/content/<lang> \
  ghcr.io/appliedepi/aedockerpublic/epirhandbook-<group>:2.9 \
  build_one_chapter.sh <stem>.qmd
```

Every language is its own Quarto book project. Its `content/<lang>/_quarto.yaml` holds the language, the title, the chapter list, the navbar and the cross-links. So a single-chapter render produces a page with full navigation, **but only when the render runs inside that project.**

The caller MUST start the render inside the project. The output directory `html_outputs/`, the sidebar and the cross-links are all project-level settings. A render started in a different directory gets none of them. `quarto render` then exits 0 and writes a standalone page next to its source. That page has no book navigation and its own copy of the asset tree. So an exit code of 0 does not prove a correct render.

**A chapter MUST render without network access.** `build_all_chapters.sh` starts every chapter container with `--network none`. A chapter that fetches something during the render, such as map tiles, fails the build. A chapter that installs a missing package during the render also fails, for example with `pacman::p_load()`. Add that package to the chapter's package list instead. The GIS chapter shows how to handle data. It reads a saved basemap from the handbook's `data/gis/`, and it shows the code that fetched the basemap without running it.

**Every chunk warning goes to the build log.** `build_all_chapters.sh` also sets `R_PROFILE_USER=/usr/local/lib/ehb/warnings_to_log.R`. `epirhandbook-common` installs [`common/warnings_to_log.R`](common/warnings_to_log.R) at that path. Each R warning that a chunk raises writes one line, `EHB-WARNING<TAB><input file><TAB><chunk label><TAB><message>`. This is true when `warning` is true, false or NA, in the chunk or for the whole document. Each error that an `error: true` chunk captures writes an `EHB-ERROR` line. These lines are a report, and they do not fail the build. The header of that file lists the cases it does not cover, such as a chunk from the knitr cache. The profile also reads a `.Rprofile` in the working directory, as R does without `R_PROFILE_USER`.

## Assembling the book

`common/build_all_chapters.sh` controls the render of the whole book. It runs on the CI runner, not inside a container, because it starts one container for each chapter render. But it is stored in `epirhandbook-common`, so that it has one source of truth. CI extracts it first:

```bash
docker run --rm <common-image> cat /usr/local/bin/build_all_chapters.sh > build_all.sh
```

It reads the language list from the handbook's `languages.yml`: `main`, and a `code` for each entry of `languages`. It reads the mapping from chapter to image from the handbook's `docker-images.yml`. These cases fail the build:

- a book chapter with no manifest row
- a language whose `_quarto.yaml` has a different chapter list from the main language's
- a language whose `_quarto.yaml` has a different chapter order from the main language's

### Four rules the build MUST follow

Experiments found each rule. If the build breaks any of them, the site is broken, but **every render still exits zero**.

1. **Render each chapter from inside its own language project.** See "Rendering one chapter" for the failure that otherwise occurs.
2. **Render every chapter twice.** A chapter rendered before its cross-reference target registers in `.quarto/xref` gets a dead same-page anchor. Without a second pass, nothing renders it again. The second pass resolves these anchors.
3. **Render one chapter at a time within a language, into one shared directory.** This lets Quarto build the search index across separate container runs. For this reason there is no `merge_search.sh`. Parallel renders would race on `search.json`. Different languages are independent and MAY run in parallel.
4. **Add the language switcher after the render.** The render does not produce it. `common/inject_language_links.R` adds the dropdown in a separate pass over the assembled site.

Each language renders in its own copy of the checkout. That copy excludes any `html_outputs/`, `.quarto/` and `*_files/` that the source already holds. So a stale local render cannot pass the validation below when no container has started.

Every language assembles to its own `<lang>/` directory, the main language included. The site root holds only `images/` and a four-line redirect stub to the main language.

`build_all_chapters.sh` validates its own output and does not rely on exit codes. It checks that every expected page exists, and that the search index refers to each page. It **fails** on a dead same-page fragment: an `href="#x"` with no `id="x"` on the same page. It names each one as `<page>#<fragment>`. It also fails when it cannot count them. The 2.7 render of the whole book, 49 chapters, had 106 dead fragments, and all were content bugs. A handbook that still has such bugs fails here until they are fixed.

[`common/test_fixture/`](common/test_fixture/) is a two-chapter handbook that the script accepts. Its README lists the variants that test the network rule, the warning log and the fragment check.

`--only-lang <code>` renders one language, for one leg of a CI matrix. The site of that language goes to the root of the output directory, with no `<lang>/` directory, no `images/` copy and no stub. It needs `--no-inject`, and does not run without it. The switcher works on the assembled site, so it runs once, after the legs are joined.

## What is not here

- **No chapter content.** The `.qmd` files, the data and `docker-images.yml` live in [`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook).
- **No older line.** 2.5, 2.6, 2.7 and 2.8 are frozen in git history, and nothing builds them.
- **No package version.** Versions come from the dated CRAN snapshot that the `rbase` tag sets. See "How dependencies resolve" in the root README.
