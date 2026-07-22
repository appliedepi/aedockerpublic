#!/bin/bash
# Phase 3 per-chapter render loop. Runs INSIDE the epirhandbook:2.5-p2ubuntu
# container, invoked as:
#   docker run --rm -e RENV_CONFIG_AUTOLOADER_ENABLED=FALSE \
#     -v <render_p3>:/book -v <p3-evidence-dir>:/p3 -w /book \
#     epirhandbook:2.5-p2ubuntu bash render_chapters.sh
#
# cwd is /book (the render_p3 working copy, a `cp -a` of render_sep18 with
# html_outputs/ deleted first). /p3 is a second bind mount used only for
# evidence output (render log, per-chapter logs, package footprints) so
# nothing needs to be copied out of the container afterward, and so nothing
# written for evidence purposes lands inside /book where quarto's own
# project/book machinery could see or copy it.
#
# Renders each English chapter in new_pages/ on its own
# (`quarto render new_pages/<chapter>.qmd`), plus index.qmd (which lives at
# the project root, not under new_pages/). Per-chapter package footprints
# are captured by the .Rprofile + capture_footprint.R hook (see
# capture_footprint.R for the mechanism) -- THIS script installs that hook
# (writes .Rprofile) and PROVES it is active with a canary knit before the
# per-chapter loop below starts, failing loudly if it is not (see the block
# right after `cd /book`). capture_footprint.R itself must already be
# present in cwd (copied in as part of working-copy setup, same as this
# script); this script does not write capture_footprint.R's content, only
# .Rprofile. Beyond installing/asserting the hook, this script only drives
# quarto and records the render outcome (OK/FAIL, elapsed seconds, a
# one-line error signature grepped from the chapter's own log).
#
# Chapter list: same filter render_full.sh (Phase 2) used --
# `ls new_pages/*.qmd | grep -vE '\.[a-z][a-z]\.qmd$'` -- i.e. every .qmd in
# new_pages/ whose name does NOT end in a 2-letter language suffix
# (.fr.qmd, .es.qmd, ...). This is EVERY English .qmd physically present,
# not just the ~49 wired into the book's `chapters:` list in _quarto.yml --
# deliberately, so chapters excluded from the book (gis, plot_continuous,
# plot_discrete, relational_databases, rstudio_advanced) and orphaned
# .qmd files never wired into any book (the `cat_*.qmd` PART-divider stubs,
# apply_functions, descriptive_statistics, modeling) are attempted too. See
# README.md for the classification of all of these.
#
# Timeout: 600s/chapter via `timeout`. This guards `gis`, which fetches live
# OpenStreetMap tiles at render time (a network call with no guaranteed
# bound) -- every other chapter renders in well under a minute in testing,
# so this ceiling should never bind for real content.
set -u
cd /book

# --- Footprint-capture hook: install, then PROVE it is genuinely active ---
# (round-2 remediation, Task 4: this script used to just assume a .Rprofile
# was "already installed" by hand, and no .Rprofile was ever committed to
# the repo -- so the capture workflow could not be reproduced from the repo
# alone. This block makes it self-sufficient: starting from nothing but a
# pristine render_sep18 copy plus this script and capture_footprint.R (both
# committed in epirhandbook/2.5/chapters/, the same as this script), it
# installs .Rprofile itself and proves the hook fires before spending time
# rendering 66 chapters.)
if [ ! -f capture_footprint.R ]; then
  echo "FATAL: capture_footprint.R not found in $(pwd) -- cannot install the footprint-capture hook." >&2
  exit 1
fi

# Install: write .Rprofile unconditionally, so this is reproducible from a
# bare render_sep18 copy plus this script and capture_footprint.R -- no
# manual "someone already placed a .Rprofile here" step required. Content
# matches epirhandbook/2.5/chapters/.Rprofile (also committed) exactly.
cat > .Rprofile <<'RPROFILE_EOF'
if (file.exists("capture_footprint.R")) source("capture_footprint.R")
RPROFILE_EOF

# Assert by OBSERVING THE REAL EFFECT, not by introspecting knitr's hook
# registry: knitr always has a default (identity) "document" hook already
# registered even with NO .Rprofile at all (verified empirically:
# `function(x) x` from <environment: namespace:base>), so "is *a* hook
# registered" is not a valid test -- only "did OUR hook actually write a
# footprint file" is. Render a throwaway one-chunk document via knitr
# directly (no need for the full quarto/book machinery for this) and check
# /p3/footprints/ for its output; verified this discriminates correctly
# (fires when .Rprofile+capture_footprint.R are present, does not when they
# are absent) before relying on it here.
CANARY=_hook_canary
rm -f "$CANARY.Rmd" "$CANARY.md" "/p3/footprints/$CANARY.txt"
printf '```{r}\n1+1\n```\n' > "$CANARY.Rmd"
Rscript -e "knitr::knit('$CANARY.Rmd', quiet=TRUE)" > /tmp/hook_check.log 2>&1
HOOK_OK=0
[ -f "/p3/footprints/$CANARY.txt" ] && HOOK_OK=1
rm -f "$CANARY.Rmd" "$CANARY.md" "/p3/footprints/$CANARY.txt"
if [ "$HOOK_OK" != "1" ]; then
  echo "FATAL: footprint-capture hook did NOT fire (expected /p3/footprints/$CANARY.txt after a canary knit; it never appeared)." >&2
  echo "--- canary knit output ---" >&2
  cat /tmp/hook_check.log >&2
  exit 1
fi
echo "### FOOTPRINT-HOOK-ACTIVE"

TIMEOUT=600
RESULTS=/p3/render_log.tsv
LOGDIR=/p3/logs
mkdir -p "$LOGDIR"
printf 'chapter\tstatus\tseconds\tnote\n' > "$RESULTS"

CHAPTERS=$(ls new_pages/*.qmd | grep -vE '\.[a-z][a-z]\.qmd$' | xargs -n1 basename | sed 's/\.qmd$//')
CHAPTERS="index $CHAPTERS"
N=$(echo $CHAPTERS | wc -w)
echo "### CHAPTER-COUNT $N"

for ch in $CHAPTERS; do
  if [ "$ch" = "index" ]; then
    target="index.qmd"
  else
    target="new_pages/$ch.qmd"
  fi
  s=$SECONDS
  timeout ${TIMEOUT}s quarto render "$target" > "$LOGDIR/$ch.log" 2>&1
  rc=$?
  secs=$((SECONDS - s))
  if [ $rc -eq 0 ]; then
    printf '%s\tOK\t%s\t\n' "$ch" "$secs" >> "$RESULTS"
    echo "### OK $ch ${secs}s"
  elif [ $rc -eq 124 ]; then
    printf '%s\tFAIL\t%s\tTIMEOUT after %ss\n' "$ch" "$secs" "$TIMEOUT" >> "$RESULTS"
    echo "### FAIL $ch ${secs}s :: TIMEOUT after ${TIMEOUT}s"
  else
    err=$(grep -oiE "could not find function .[a-zA-Z0-9_.]+.|object .[^ ]+. not found|cannot open|no such file|there is no package|Error in [^:]{0,60}|Error:.{0,80}" "$LOGDIR/$ch.log" | tail -1 | tr '\t' ' ')
    printf '%s\tFAIL\t%s\t%s\n' "$ch" "$secs" "$err" >> "$RESULTS"
    echo "### FAIL $ch ${secs}s :: $err"
  fi
done
echo "### ALL-DONE"
