# syntax=docker/dockerfile:1
# epirhandbook-checks:2.9: the image that the handbook's translation sync
# check runs in (.github/workflows/translation-sync.yml in
# appliedepi/epirhandbook). It renders no chapter.
#
# The check needs git, python3 with PyYAML, Quarto, and R with knitr and
# rmarkdown. epirhandbook-common carries Quarto, R, knitr and rmarkdown. This
# file adds the rest, so the check installs nothing when it runs. On
# 2026-10-23 an apt install on the bare runner hung for 5 hours 20 minutes.
# The checks call pandoc through `quarto pandoc`, so pandoc needs no install
# of its own.
ARG BASE_IMAGE=epirhandbook-common:2.9
FROM ${BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends git python3 python3-yaml \
    && rm -rf /var/lib/apt/lists/*

# --- Build-time check: every tool that the sync check calls is here.
RUN git --version \
    && python3 -c "import yaml; print('PyYAML', yaml.__version__)" \
    && quarto --version \
    && quarto pandoc --version >/dev/null \
    && R -q -e "stopifnot(requireNamespace('knitr', quietly = TRUE), requireNamespace('rmarkdown', quietly = TRUE))"
