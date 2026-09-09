# epiRhandbook 2.8: the group images

2.8 publishes one shared `epirhandbook-common` image, six group images, and a monolith, all on the
2026 package stack (R 4.6.0). Each image is a package environment. Chapter content is rendered at
runtime from mounted `.qmd` files, never baked in.

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
python3 epirhandbook/2.8/generate_groups.py           # write the seven lists
python3 epirhandbook/2.8/generate_groups.py --check   # regenerate in memory, fail on a difference
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
image inherits it. It renders ONE `.qmd`, passed as an argument, with the book content mounted at
the working directory:

```bash
docker run --rm -v <book>:/book -w /book \
  ghcr.io/appliedepi/aedockerpublic/epirhandbook-<group>:2.8 \
  build_one_chapter.sh chapters/<stem>.qmd
```

The navbar, the sidebar and the cross-links all come from `_quarto.yml`, which is part of the
mounted content. A single-chapter render therefore produces a page with complete navigation,
**provided `_quarto.yml` already matches the language of the file being rendered.**

That proviso is the caller's job. Rendering `chapters/basics.fr.qmd` against the English
`_quarto.yml` fails silently. `quarto render` exits 0, but the page lands outside `html_outputs/`.
It carries the bare filename as its title, the tag `lang="en"`, no sidebar, and its own duplicated
asset tree. `common/rewrite_lang_config.R` rewrites `_quarto.yml` for one language and must run
first. An exit code is not evidence here.

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

It reads the language list from `_quarto.yml` (`babelquarto.mainlanguage` and
`babelquarto.languages`) and the chapter-to-image mapping from the handbook repository's
`docker-images.yml`. A book chapter with no manifest row fails the build.

### Four rules the build must obey

Each was established by experiment. Breaking any of them produces a broken site in which **every
render still exits zero**.

1. **Rewrite `_quarto.yml` for a language before rendering that language.** See the silent failure
   described above.
2. **Render every chapter twice.** A chapter rendered before its cross-reference target registers
   in `.quarto/xref` emits a dead same-page anchor. It is never re-rendered. The second pass
   resolves them.
3. **Render sequentially within a language, into one shared directory.** That is what lets Quarto
   accumulate the search index across separate container runs. It is also why there is no
   `merge_search.sh`. Parallel renders would race on `search.json`. Different languages are
   independent and may run in parallel.
4. **Inject the language switcher afterwards.** Rendering never produces it.
   `common/inject_language_links.R` adds the dropdown, as a post-pass over the assembled site.

Start each language from a pristine copy of the checkout. `rewrite_lang_config.R` is not
idempotent, and it *moves* rather than copies the English source when a translation is missing.
English assembles to the site root, and every other language to `<lang>/`.

`build_all_chapters.sh` validates its own output rather than trusting exit codes: every expected
page exists, and the search index references each one. It also **reports** dead same-page
fragments without failing on them. The 2.7 whole-book reference render of 49 chapters contains
106 of its own. They are pre-existing content bugs, so a gate there would fail every build
forever.

## What is not here

- **No chapter content.** The `.qmd` files, the data and `docker-images.yml` live in
  [`appliedepi/epirhandbook`](https://github.com/appliedepi/epirhandbook).
- **No older line.** 2.5, 2.6 and 2.7 are frozen under
  [`../../archive/`](../../archive/README.md) and nothing builds them.
- **No package version.** Versions come from the dated CRAN snapshot that `rbase`'s tag owns. See
  the root README's "How dependencies resolve".
