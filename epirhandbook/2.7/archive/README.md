# Archive: how the 2.7 package lists were originally derived

**These files are not run any more.** `images.yaml`, `packages_cran.txt` (per chapter and in
`common/`) and `packages_github.json` are now hand-maintained sources of truth. A human edits them
directly. Nothing in this repository regenerates them.

This directory keeps `generate.py`, `footprints.tsv` and `frequency.tsv` only as a record of the
method that produced the first version of those files. Read on if you want to know how the numbers
were derived, or if you are tempted to run `generate.py` again.

## What these files are

- **`footprints.tsv`** — one row per chapter. Each row is that chapter's `loadedNamespaces()` dump
  from an instrumented render of the handbook: the full set of R packages actually loaded while
  rendering that chapter, measured directly rather than declared.
- **`frequency.tsv`** — `footprints.tsv`, counted. For every package name, it counts how many of
  the 48 chapters loaded it. That count decided which packages went into the shared
  `epirhandbook-common` image (loaded by most chapters) versus a per-chapter delta (loaded by few).
- **`generate.py`** — the script that read `footprints.tsv` and `frequency.tsv`, split the package
  set into common vs. per-chapter, and wrote `epirhandbook/2.7/images.yaml`, `common/Dockerfile`,
  `common/packages_cran.txt`, and each chapter's `Dockerfile` and `packages_cran.txt`.

## Do not run this again

`generate.py` is kept as a record of method, not as a tool to run. Its own header lists its
remaining inputs, and two of them are no longer in this directory:

- `footprints.tsv` and `frequency.tsv` — now here, in `archive/`, not at
  `epirhandbook/2.7/`.
- `packages_github.json` — still at `epirhandbook/2.7/packages_github.json`. Not moved, because it
  is one of the hand-maintained files this archiving is protecting, not a generator input to
  discard.
- `verify_render_26.04.tsv` — deliberately left at `epirhandbook/2.7/verify_render_26.04.tsv`. It
  is a verification record for the 2.7 forward-port, useful on its own, not just an input to this
  generator.

Because of this, `generate.py`'s inputs are no longer all in one place — one is here in
`archive/`, one is in the parent directory. If you copied `generate.py` back to
`epirhandbook/2.7/` and ran it, it would still find `packages_github.json` and
`verify_render_26.04.tsv` next to it, but not `footprints.tsv` or `frequency.tsv` — it would fail
to find its own inputs, or, if you also copied those back, it would overwrite every hand-made edit
made to `images.yaml`, the per-chapter Dockerfiles, and every `packages_cran.txt` since 2.7 shipped.

## How to do today what the generator used to do

To add a package to a chapter, edit that chapter's `packages_cran.txt` by hand, one line per
package.
