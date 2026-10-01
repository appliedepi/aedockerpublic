# Test fixture for `build_all_chapters.sh`

This directory is a one-language handbook that `build_all_chapters.sh` accepts. Its book has two
chapters, `index` and `scenario`. As committed, `scenario` is clean: the build exits 0 and logs no
`EHB-` line.

Each directory under `variants/` holds a replacement for `content/en/scenario.qmd`, and
sometimes a `.Rprofile`. Copy the fixture, then copy one variant over `content/en/`:

```bash
cp -a test_fixture /tmp/fx
cp -a test_fixture/variants/warning_false/. /tmp/fx/content/en/
```

| Variant | What the build MUST do |
|---|---|
| `missing_package` | exit non-zero, because the render has no network to install `praise` |
| `nonexistent_package` | exit non-zero, because `pacman::p_load()` stops with no network |
| `warning_false` | log 1 `EHB-WARNING` line per render of `scenario` |
| `warning_true` | log 3, and show the warnings on the page |
| `warning_doclevel` | log 12 |
| `warning_na` | log 1 |
| `message_only` | log 0 |
| `error_true` | log 1 `EHB-ERROR` line and 0 `EHB-WARNING` lines |
| `dead_fragment` | exit non-zero, and name `scenario.html#nope` |
| `rprofile` | show `RPROFILE-SOURCED` on the page |

The build renders every chapter twice, so the log holds each `EHB-` line once per pass. Quarto
puts an ANSI colour code in front of the line. Count after you strip it:

```bash
sed 's/\x1b\[[0-9;]*m//g' build.log | grep -c '^EHB-WARNING'
```

`docker-images.yml` names `epirhandbook-common:2.9` for both chapters. To test a local image, edit
the `image:` lines in your copy, and pass a registry prefix that matches the local tag.
