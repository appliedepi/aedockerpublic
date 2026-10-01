# epiRhandbook 2.9: the group images

2.9 publishes one shared `epirhandbook-common` image, six group images, and a monolith, all on the
2026 package stack (R 4.6.0). Each image is a package environment. Chapter content is rendered at
runtime from mounted `.qmd` files, never baked in.

2.9 carries the same nine images and the same package lists as 2.8. What changed is the handbook
layout the render scripts drive: every language is now its own Quarto book project, at
`content/<lang>/`. 2.8 is in git history, not in the working tree.

This file covers the mechanics of this directory. The
[root README](../../README.md) covers the catalogue, the build trigger, and what each image is
for.

## How packages install

Every chapter owns a package list, `groups/<group>/packages_cran_<stem>.txt`: one bare CRAN or
Bioconductor name per line. There are 50 of them, one per chapter.
`groups/miscellaneous/packages_cran_errors.txt` is empty, because that chapter runs no R.

The list sits in the directory of the group image that renders the chapter. That location assigns
the chapter to the group, so no separate assignment file exists. The assignment itself stays an
editorial decision: `gis` joined `analysis` because it sits in the book's Analysis part.

[`generate_groups.py`](generate_groups.py) derives seven lists from those 50: one
`groups/<group>/packages_cran.txt` per group, and `monolith/packages_cran.txt`. A group's list is
the plain union of its member chapters' full lists. The monolith's list is the union of the six.
A group's generated list is the file with no `_<stem>` in its name.
**Never hand-edit a generated list.** Edit the input and rerun the generator:

```bash
python3 epirhandbook/2.9/generate_groups.py           # write the seven lists
python3 epirhandbook/2.9/generate_groups.py --check   # regenerate in memory, fail on a difference
```

Both modes check the layout against [`images.yaml`](images.yaml) first, group by group. Every
chapter a group image lists under `renders` must own a package list in that image's own directory.
Every package list in that directory must belong to a chapter that image renders. A chapter filed
under the wrong group therefore fails the check, even when its list is empty and no generated list
moves.

CI runs `--check` twice: in `checks.yml` on every pull request and push, and in `build.yml`'s plan
job before any image builds. A stale list fails both.

[`packages_github.json`](packages_github.json) holds the 7 GitHub-pinned packages, each with a
commit SHA. `epirhandbook-common` installs all 7, so every group image inherits them. A
transitively pulled GitHub package then resolves to its pinned commit instead of coming from
CRAN.

[`pak_install_subset.R`](pak_install_subset.R) does every install. It reads a CRAN list and, for
`epirhandbook-common` only, the pin file, then runs `pak::pkg_install(refs, dependencies = NA)`.
There is no hand-computed dependency closure.

A group image is FROM `epirhandbook-common` and installs its group's **full** list on top, not a
pre-subtracted delta. pak skips what common already holds, so the image is a superset of every
member chapter's footprint by construction. Every group Dockerfile ends with a build-time
invariant: every package in its own `packages_cran.txt` must load, or the build fails.

The per-chapter lists were derived once, from an instrumented render that recorded
`loadedNamespaces()` for each chapter. 48 of them were captured for 2.7 and copied here unchanged
on 2026-09-02, and `gis` was captured the same way in 2.8. The `errors` chapter needed no capture,
which accounts for all 50. That derivation is finished, and its
generator was removed with the rest of the archived lines. Read it out of git history if you need it. **Do not run it.**

## Rendering one chapter

`common/build_one_chapter.sh` is installed onto `PATH` in `epirhandbook-common`, so every group
image inherits it. It renders ONE `.qmd`, passed as an argument, with the book content mounted and
that chapter's own language project as the working directory:

```bash
docker run --rm -v <book>:/book -w /book/content/<lang> \
  ghcr.io/appliedepi/aedockerpublic/epirhandbook-<group>:2.9 \
  build_one_chapter.sh <stem>.qmd
```

Every language is its own Quarto book project. Its `content/<lang>/_quarto.yaml` carries the
language, the title, the chapter list, the navbar and the cross-links. A single-chapter render
therefore produces a page with complete navigation, **provided the render runs inside that
project.**

That proviso is the caller's job. The output directory `html_outputs/`, the sidebar and the
cross-links are all project-level settings, so a render started anywhere else gets none of them.
`quarto render` exits 0 and writes a standalone page beside its source, with no book navigation
and its own duplicated asset tree. An exit code is not evidence here.

**A chapter MUST render without network access.** `build_all_chapters.sh` starts every chapter
container with `--network none`. A chapter that fetches something while it renders, such as map
tiles, fails the build. So does a chapter that installs a missing package while it renders, for
example with `pacman::p_load()`. Add that package to the chapter's package list instead. The GIS
chapter is the precedent for data. It reads a saved basemap from the handbook's `data/gis/`, and
it shows the code that fetched the basemap without running it.

**Every chunk warning reaches the build log.** `build_all_chapters.sh` also sets
`R_PROFILE_USER=/usr/local/lib/ehb/warnings_to_log.R`, where `epirhandbook-common` installs
[`common/warnings_to_log.R`](common/warnings_to_log.R). Each R warning that a chunk raises writes
one line, `EHB-WARNING<TAB><input file><TAB><chunk label><TAB><message>`. That holds for `warning`
set to true, false or NA, in the chunk or for the whole document. Each error that an `error: true`
chunk captures writes an `EHB-ERROR` line. The lines are a report and do not fail the build. The
header of that file lists what it does not cover, such as a chunk served from the knitr cache. The
profile also reads a `.Rprofile` in the working directory, as R does without `R_PROFILE_USER`.

## Assembling the book

`common/build_all_chapters.sh` orchestrates the whole book. It runs on the CI runner, not inside a
container, because it starts one container per chapter render. It is nonetheless stored in
`epirhandbook-common`, so there is one source of truth for it, and CI extracts it first:

```bash
docker run --rm <common-image> cat /usr/local/bin/build_all_chapters.sh > build_all.sh
```

It reads the language list from the handbook's `languages.yml` (`main`, and a `code` per entry of
`languages`) and the chapter-to-image mapping from the handbook's `docker-images.yml`. A book
chapter with no manifest row fails the build. So does a language whose `_quarto.yaml` declares a
different chapter list, or a different chapter order, from the main language's.

### Four rules the build must obey

Each was established by experiment. Breaking any of them produces a broken site in which **every
render still exits zero**.

1. **Render each chapter from inside its own language project.** See the silent failure described
   above.
2. **Render every chapter twice.** A chapter rendered before its cross-reference target registers
   in `.quarto/xref` emits a dead same-page anchor. It is never re-rendered. The second pass
   resolves them.
3. **Render sequentially within a language, into one shared directory.** That is what lets Quarto
   accumulate the search index across separate container runs. It is also why there is no
   `merge_search.sh`. Parallel renders would race on `search.json`. Different languages are
   independent and may run in parallel.
4. **Inject the language switcher afterwards.** Rendering never produces it.
   `common/inject_language_links.R` adds the dropdown, as a post-pass over the assembled site.

Each language renders in its own copy of the checkout, and that copy excludes any `html_outputs/`,
`.quarto/` and `*_files/` the source already holds. A stale local render then cannot satisfy the
validation below without a single container ever starting.

Every language assembles to its own `<lang>/` directory, the main language included. The site root
holds `images/` and a four-line redirect stub to the main language, and nothing else.

`build_all_chapters.sh` validates its own output rather than trusting exit codes: every expected
page exists, and the search index references each one. It also **fails** on a dead same-page
fragment, an `href="#x"` with no `id="x"` on the same page, and names each one as
`<page>#<fragment>`. It fails when it cannot count them, too. The 2.7 whole-book render of 49
chapters held 106 dead fragments, all content bugs. A handbook that still holds such bugs fails
here until they are fixed.

[`common/test_fixture/`](common/test_fixture/) is a two-chapter handbook that the script accepts.
Its README lists the variants that test the network rule, the warning log and the fragment check.

`--only-lang <code>` renders one language, for one leg of a CI matrix. That language's site lands
at the root of the output directory, with no `<lang>/` nesting, no `images/` copy and no stub. It
requires `--no-inject`, and refuses to run without it. The switcher is defined over the assembled
site, so it runs once, after the legs are joined.

## What is not here

- **No chapter content.** The `.qmd` files, the data and `docker-images.yml` live in
  [`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook).
- **No older line.** 2.5, 2.6, 2.7 and 2.8 are frozen under
  git history and nothing builds them.
- **No package version.** Versions come from the dated CRAN snapshot that `rbase`'s tag owns. See
  the root README's "How dependencies resolve".
