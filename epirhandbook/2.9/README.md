# epiRhandbook 2.9: the group images

2.9 publishes one shared `epirhandbook-common` image, six group images, and a monolith, all on the
2026 package stack (R 4.6.0). Each image is a package environment. Chapter content is rendered at
runtime from mounted `.qmd` files, never baked in.

2.9 carries the same nine images and the same package lists as 2.8. What changed is the handbook
layout the render scripts drive: every language is now its own Quarto book project, at
`content/<lang>/`. 2.8 is frozen under [`../../archive/`](../../archive/README.md).

This file covers the mechanics of this directory. The
[root README](../../README.md) covers the catalogue, the build trigger, and what each image is
for.

## How packages install

Every chapter owns a package list, `chapters/<stem>/packages_cran.txt`: one bare CRAN or
Bioconductor name per line. There are 50 of them, one per chapter. `chapters/errors/` holds an
empty file, because that chapter runs no R.

[`groups.yaml`](groups.yaml) assigns each chapter to exactly one group. It is hand-maintained,
because the assignment is an editorial decision.

[`generate_groups.py`](generate_groups.py) derives seven lists from those two inputs: one
`groups/<group>/packages_cran.txt` per group, and `monolith/packages_cran.txt`. A group's list is
the plain union of its member chapters' full lists. The monolith's list is the union of the six.
**Never hand-edit a generated list.** Edit the input and rerun the generator:

```bash
python3 epirhandbook/2.9/generate_groups.py           # write the seven lists
python3 epirhandbook/2.9/generate_groups.py --check   # regenerate in memory, fail on a difference
```

CI runs `--check` twice: in `checks.yml` on every pull request and push, and in `build.yml`'s plan
job before any image builds. A stale list fails both.

[`packages_github.json`](packages_github.json) holds the 6 GitHub-pinned packages, each with a
commit SHA. `epirhandbook-common` installs all 6, so every group image inherits them. A
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
generator is frozen at `../../archive/epirhandbook/2.7/archive/`. **Do not run it.**

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

**A chapter must also render without network access.** CI renders inside a container that reaches
only the registry, so a chapter that fetches something while it renders, such as map tiles, fails
there. The GIS chapter is the precedent: it reads a saved basemap from the handbook's `data/gis/`
and shows, without running, the code that fetched it. Prove a new chapter the same way, with
`docker run --network none`.

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
page exists, and the search index references each one. It also **reports** dead same-page
fragments without failing on them. The 2.7 whole-book reference render of 49 chapters contains
106 of its own. They are pre-existing content bugs, so a gate there would fail every build
forever.

`--only-lang <code>` renders one language, for one leg of a CI matrix. That language's site lands
at the root of the output directory, with no `<lang>/` nesting, no `images/` copy and no stub. It
requires `--no-inject`, and refuses to run without it. The switcher is defined over the assembled
site, so it runs once, after the legs are joined.

## What is not here

- **No chapter content.** The `.qmd` files, the data and `docker-images.yml` live in
  [`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook).
- **No older line.** 2.5, 2.6, 2.7 and 2.8 are frozen under
  [`../../archive/`](../../archive/README.md) and nothing builds them.
- **No package version.** Versions come from the dated CRAN snapshot that `rbase`'s tag owns. See
  the root README's "How dependencies resolve".
