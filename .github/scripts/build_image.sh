#!/bin/bash
# Build one image from the CI plan. In "publish" mode, also push it.
# If the image has a base, the script asks the registry for the base's digest
# at build time. A base that this run also rebuilt resolves from the image the
# run pushed. Any other base resolves from its published tag. Between the
# build and any push, the script renders a smoke document in the image (see
# "Smoke render" below).
#
# Usage:
#   build_image.sh <mode> <repo_lowercased> <name> <dir> <tags_csv> \
#                   <base_name> <base_tag> <base_freshly_built> \
#                   <git_commit> <context> <description>
# For an image with no base, such as rbase, base_name and base_tag are empty
# strings and base_freshly_built is "false". <context> defaults to <dir> when
# omitted (see CONTEXT below). <description> is the one-line description from
# the image's catalog record. It is REQUIRED (see DESCRIPTION below).
#
# <mode> is "publish" or "verify":
#   publish: the path build.yml uses to publish. The script tags the image as
#     $REGISTRY/<repo>/<name>:<tag> for every tag and pushes every tag. It
#     needs a prior `docker login` to $REGISTRY. A freshly built base resolves
#     from the registry. An earlier job in this run pushed it, possibly on a
#     different runner (see the base-resolution block below).
#   verify: a drift check or local dry run. It builds the same Dockerfile with
#     the same base-resolution rules, but never pushes. A freshly built base is
#     referenced by its plain local tag, with no registry round trip. The image
#     built here gets tags without the registry prefix, because it is never
#     pushed. This mode needs no registry login: the only registry access is a
#     read of a published public base. Nothing in this repo runs "verify" on a
#     schedule. A maintainer can run it by hand, for example for the
#     local-registry rehearsal in CHANGELOG.md.
#
# GIT_COMMIT is the anchor for per-image change detection. The script stamps it
# on the image as the org.opencontainers.image.revision label. It also stamps
# org.opencontainers.image.source, which it derives from REPO as
# "https://github.com/$REPO". On the next run, .github/scripts/changed_images.py
# reads these labels with a metadata-only `docker buildx imagetools inspect`,
# never a `docker pull`. It marks the image as changed when the image was never
# published or has no revision label. Otherwise it runs `git diff` since that
# commit over the image's own dir, the shared build inputs and the .github/
# machinery. An image with a base also carries
# org.opencontainers.image.base.digest (see LABEL_ARGS below). That label finds
# a base that moved after this image was built (see the header of
# changed_images.py).
# A missing or empty GIT_COMMIT is a hard error (below). With an empty
# revision label, changed_images.py would mark this image as changed on every
# future run. Nothing would show the fault except the extra rebuilds.
#
# REGISTRY defaults to ghcr.io. To test against a throwaway registry, set it in
# the environment, for example REGISTRY=localhost:5000.
#
# GITHUB_PAT is OPTIONAL. When it is set, the script passes it to
# `docker build` as a BuildKit secret (--secret id=github_pat,env=GITHUB_PAT).
# It MUST NOT be a --build-arg: a build-arg shows in `docker history` even when
# no ENV uses it. This project's own rule forbids that leak (see the
# maintainer section of README.md and the comment in the Dockerfile).
# The token only raises pak's GitHub API rate limit. pak needs the API to
# resolve the GitHub-SHA-pinned packages in the epirhandbook build, which is a
# read of repo contents. So the caller (build.yml) MUST take it from a
# credential scoped to public read only (the `GH_READONLY_PAT` repository
# secret). It MUST NOT be a token that also holds `packages: write`. The build
# installs 473 packages, and several compile from source with their own
# post-install scripts. That code must never run with a credential that can
# push to the registry.
# If GITHUB_PAT is unset or empty, the script builds with no token. It never
# substitutes a different credential with more privilege. The GitHub lookups
# then use the anonymous GitHub API rate limit. That is enough in normal
# operation. CHANGELOG.md records what happens on a shared runner IP.
set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io}"

MODE="$1"; shift
case "$MODE" in
  publish|verify) ;;
  *)
    echo "::error::build_image.sh: unknown mode '$MODE' (expected 'publish' or 'verify')" >&2
    exit 1
    ;;
esac

REPO="$1"; NAME="$2"; DIR="$3"; TAGS_CSV="$4"
BASE_NAME="$5"; BASE_TAG="$6"; BASE_FRESH="$7"
GIT_COMMIT="$8"
if [ -z "$GIT_COMMIT" ]; then
  echo "::error::build_image.sh: no git commit given (arg 8) -- every build must stamp org.opencontainers.image.revision, or changed_images.py can never resolve this image's last-published commit and will treat it as changed on every future run." >&2
  exit 1
fi
# The docker build CONTEXT. It defaults to DIR, which today applies to rbase
# alone: its COPY paths resolve against its own Dockerfile's directory.
# Each of the eight images in epirhandbook/2.9/images.yaml passes a context.
# Their Dockerfile is in the image's own dir, but it COPYs pak_install_subset.R
# from epirhandbook/2.9. So the context is that shared root, and DIR stays
# per-image as the change-detection scope. A build with the image's own dir as
# context fails, because the COPY sources are outside it.
CONTEXT="${9:-$DIR}"

# The image's own one-line description, from its catalog record. It becomes
# the org.opencontainers.image.description label below. Keep the braces:
# $10 is $1 followed by a literal 0, which would stamp the repo name with a
# trailing zero on every image.
#
# An empty description is a hard error, as an empty GIT_COMMIT is. Without a
# value, the published image keeps the description it inherits from its base.
# For rbase, that is Canonical's text for the ubuntu image. plan.py makes
# `description` a REQUIRED catalog key, so a record cannot reach this point
# without one.
DESCRIPTION="${10:-}"
if [ -z "$DESCRIPTION" ]; then
  echo "::error::build_image.sh: no description given (arg 10) -- every build must stamp org.opencontainers.image.description, or the published image presents its base image's description as ours." >&2
  exit 1
fi

IFS=',' read -r -a TAGS <<< "$TAGS_CSV"

BUILD_ARGS=()

# Date-stamped tag -> CRAN_SNAPSHOT_DATE build-arg. If the first tag ends in
# YYYY-MM-DD (rbase's "4.6.0-2026-07-01"), that date is the only source for the
# pinned CRAN snapshot. The script passes it as a build-arg, and the Dockerfile
# derives the snapshot URL from it (rbase/4.6.0/Dockerfile). The rule applies
# to every image, not only rbase. A tag with no date suffix, such as a group
# image's "2.9", does not match. Then no arg is passed, and no Dockerfile
# reads one.
if [[ "${TAGS[0]}" =~ -([0-9]{4}-[0-9]{2}-[0-9]{2})$ ]]; then
  BUILD_ARGS+=(--build-arg "CRAN_SNAPSHOT_DATE=${BASH_REMATCH[1]}")
  echo "$NAME: tag '${TAGS[0]}' carries snapshot date ${BASH_REMATCH[1]} -> passing as --build-arg CRAN_SNAPSHOT_DATE"
fi

BASE_REF=""
BASE_DIGEST=""
if [ -n "$BASE_NAME" ]; then
  if [ "$BASE_FRESH" = "true" ]; then
    if [ "$MODE" = "publish" ]; then
      REG_TAG="$REGISTRY/$REPO/$BASE_NAME:$BASE_TAG"
      echo "Resolving $BASE_NAME's digest live from $REGISTRY (it was rebuilt earlier in this run): $REG_TAG"
      DIGEST="$(docker buildx imagetools inspect "$REG_TAG" | awk '/^Digest:/{print $2; exit}')"
      if [ -z "$DIGEST" ]; then
        echo "::error::Could not resolve a digest for $REG_TAG via 'docker buildx imagetools inspect' -- was it actually pushed in an earlier layer of this run?" >&2
        exit 1
      fi
      BASE_REF="$REGISTRY/$REPO/$BASE_NAME@$DIGEST"
      BASE_DIGEST="$DIGEST"
    else
      # verify mode: an earlier step of this job built the base on this
      # runner, so use its plain local tag. Nothing is pushed, so there is no
      # registry digest to resolve.
      BASE_REF="$BASE_NAME:$BASE_TAG"
      echo "Using the LOCAL image built earlier in this run: $BASE_REF (verify mode never pushes, so there is no registry digest to re-resolve)"
      # The local image id, because a local base has no registry digest.
      # No registry digest equals it, which is correct: verify never pushes.
      BASE_DIGEST="$(docker image inspect --format '{{.Id}}' "$BASE_REF")"
    fi
  else
    # This run did not rebuild the base. Under the OCI-revision change model,
    # the base is unchanged since its last publish and is in the registry. So
    # its current published tag is the correct base to build FROM, and the
    # script resolves its digest now. This lets a rerun resume a partial
    # publish: the rerun skips the unchanged base, and its dependent still
    # builds against the published base. The lookup is a registry read
    # (imagetools inspect). It never pulls, and a public image needs no login.
    #
    # Trust boundary: this assumes that only this workflow writes the registry
    # tag. If someone retags or force-pushes a base tag outside this CI run,
    # this script follows the moved tag with no warning. Nothing here checks
    # for that. It is an accepted trust boundary.
    REG_TAG="$REGISTRY/$REPO/$BASE_NAME:$BASE_TAG"
    echo "Resolving $BASE_NAME's digest live from $REGISTRY (not rebuilt this run; unchanged since last publish): $REG_TAG"
    DIGEST="$(docker buildx imagetools inspect "$REG_TAG" | awk '/^Digest:/{print $2; exit}')"
    if [ -z "$DIGEST" ]; then
      echo "::error::'$BASE_NAME' was not rebuilt this run and its tag $REG_TAG does not resolve in the registry -- the base has never been published, so '$NAME' has nothing to build FROM. The layered plan builds a base before its dependents, so this should not happen in a normal run." >&2
      exit 1
    fi
    echo "$NAME will build FROM the published $BASE_NAME at digest $DIGEST"
    BASE_REF="$REGISTRY/$REPO/$BASE_NAME@$DIGEST"
    BASE_DIGEST="$DIGEST"
  fi
  BUILD_ARGS+=(--build-arg "BASE_IMAGE=$BASE_REF")
  echo "$NAME will build FROM: $BASE_REF"
fi

TAG_ARGS=()
for t in "${TAGS[@]}"; do
  if [ "$MODE" = "publish" ]; then
    TAG_ARGS+=(-t "$REGISTRY/$REPO/$NAME:$t")
  else
    TAG_ARGS+=(-t "$NAME:$t")  # verify mode: plain local tag, never pushed
  fi
done

# org.opencontainers.image.revision and .source: see the header comment.
# REPO_URL comes from REPO, the lowercased owner/repo that every registry ref
# in this script uses. A separate argument would be one more positional to keep
# in sync. GitHub repository URLs are not case-sensitive, so the lowercase form
# resolves.
REPO_URL="https://github.com/$REPO"

# org.opencontainers.image.title/.description/.version/.created state what
# this image is. Without them, each published image keeps the four labels it
# inherits from the ubuntu base, so `docker inspect` reports the title
# "ubuntu", the version "26.04", Canonical's description and a created date
# from the ubuntu release rather than from this build.
#
# `created` is the wall-clock time of this build, so the same source builds
# to a different digest every run. A real created stamp always does that.
# changed_images.py never reads created. It does compare digests: see
# org.opencontainers.image.base.digest below. So a base rebuilt from the same
# source gets a new digest, and every image built FROM it rebuilds on the next
# run. That is the intended result: those images hold the old base's layers.
CREATED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LABEL_ARGS=(
  --label "org.opencontainers.image.revision=$GIT_COMMIT"
  --label "org.opencontainers.image.source=$REPO_URL"
  --label "org.opencontainers.image.title=$NAME"
  --label "org.opencontainers.image.description=$DESCRIPTION"
  --label "org.opencontainers.image.version=${TAGS[0]}"
  --label "org.opencontainers.image.created=$CREATED"
)
# org.opencontainers.image.base.digest: the digest of the exact base image
# this build is FROM, as resolved above. changed_images.py compares it with
# the digest the base's tag points to on the next run. A difference means
# this image was built FROM an older base, and it rebuilds. The revision
# label cannot show that: after a partial publish, this image's own diff can
# be empty while its base has moved on.
if [ -n "$BASE_NAME" ]; then
  LABEL_ARGS+=(--label "org.opencontainers.image.base.digest=$BASE_DIGEST")
fi

echo "Building $NAME from $DIR (context: $CONTEXT) with tags: ${TAGS[*]} (mode: $MODE)"
echo "Stamping org.opencontainers.image.revision=$GIT_COMMIT, org.opencontainers.image.source=$REPO_URL"
echo "Stamping org.opencontainers.image.title=$NAME, org.opencontainers.image.version=${TAGS[0]}, org.opencontainers.image.created=$CREATED"
echo "Stamping org.opencontainers.image.description=$DESCRIPTION"
if [ -n "$BASE_DIGEST" ]; then
  echo "Stamping org.opencontainers.image.base.digest=$BASE_DIGEST"
fi
if [ -n "${GITHUB_PAT:-}" ]; then
  echo "GITHUB_PAT is set (a read-only credential, or an operator-supplied token for local testing) -- passing it as a BuildKit secret."
else
  echo "GITHUB_PAT is NOT set -- building with no GitHub token at all. pak's github:: package resolution falls back to the ANONYMOUS GitHub API rate limit for any GitHub-pinned packages this build installs (see this script's header comment)."
fi
DOCKER_BUILDKIT=1 docker build \
  --secret id=github_pat,env=GITHUB_PAT \
  "${BUILD_ARGS[@]}" \
  "${LABEL_ARGS[@]}" \
  "${TAG_ARGS[@]}" \
  -f "$DIR/Dockerfile" \
  "$CONTEXT"

# --- Smoke render: before any push, and before verify mode exits ------------
# The image renders common/smoke.qmd: an R chunk that computes a value, a
# ggplot2 plot and a knitr::kable table. It runs the image's own
# build_one_chapter.sh, with no network and with the R_PROFILE_USER that
# build_all_chapters.sh gives each chapter container. The render runs in a
# new directory in the container, as the image's default user. A failed
# render, or no smoke.html, stops this script. So publish mode pushes nothing
# and verify mode exits non-zero.
#
# A pass shows that R, knitr, ggplot2, Quarto and the R profile run together
# in this image. It does not show that the image holds every package its
# chapters need, or that the profile logs warnings. build_all_chapters.sh
# and common/test_fixture check those.
#
# Skip rule: an image without an executable /usr/local/bin/build_one_chapter.sh
# renders nothing. It gets no smoke render, and the log names it. Today that
# is rbase alone. `test -x` runs in the image. Its exit 1 means the file is
# absent. Any other failure is docker's own, and it stops this script, so a
# broken docker cannot pass as a skip.
if [ "$MODE" = "publish" ]; then
  BUILT_REF="$REGISTRY/$REPO/$NAME:${TAGS[0]}"
else
  BUILT_REF="$NAME:${TAGS[0]}"
fi
SMOKE_QMD_IN_IMAGE="/usr/local/lib/ehb/smoke.qmd"            # common/Dockerfile COPYs it here
R_PROFILE_IN_IMAGE="/usr/local/lib/ehb/warnings_to_log.R"    # the same path as build_all_chapters.sh
HAS_RENDERER=0
docker run --rm --pull never --network none "$BUILT_REF" \
  test -x /usr/local/bin/build_one_chapter.sh || HAS_RENDERER=$?
case "$HAS_RENDERER" in
  0)
    echo "Smoke render: $BUILT_REF renders $SMOKE_QMD_IN_IMAGE with build_one_chapter.sh (--network none, R_PROFILE_USER=$R_PROFILE_IN_IMAGE)"
    # shellcheck disable=SC2016  # $(mktemp -d) and $1 expand in the container
    if ! docker run --rm --pull never --network none -e "R_PROFILE_USER=$R_PROFILE_IN_IMAGE" "$BUILT_REF" \
        bash -euc 'cd "$(mktemp -d)" && cp "$1" smoke.qmd && build_one_chapter.sh smoke.qmd && test -s smoke.html' \
        smoke "$SMOKE_QMD_IN_IMAGE"; then
      echo "::error::Smoke render FAILED in $BUILT_REF. Nothing was pushed. The output above shows the render error." >&2
      exit 1
    fi
    echo "Smoke render PASSED in $BUILT_REF"
    ;;
  1)
    echo "Smoke render SKIPPED for $NAME: the image has no executable /usr/local/bin/build_one_chapter.sh, so it renders nothing"
    ;;
  *)
    echo "::error::Could not check $BUILT_REF for /usr/local/bin/build_one_chapter.sh: docker run exited $HAS_RENDERER" >&2
    exit 1
    ;;
esac

if [ "$MODE" = "verify" ]; then
  LOCAL_ID="$(docker inspect --format='{{.Id}}' "$NAME:${TAGS[0]}")"
  echo "Built (NOT published) $NAME:${TAGS[0]} -- local image id: $LOCAL_ID"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
      echo "### Verified \`$NAME\` (drift check -- not published)"
      echo ""
      echo "- Tags built locally: ${TAGS[*]}"
      echo "- Local image id: \`$LOCAL_ID\`"
      echo ""
    } >> "$GITHUB_STEP_SUMMARY"
  fi
  exit 0
fi

# --- publish mode only, from here on ---------------------------------------
FIRST_REF="$REGISTRY/$REPO/$NAME:${TAGS[0]}"
for t in "${TAGS[@]}"; do
  echo "Pushing $REGISTRY/$REPO/$NAME:$t"
  docker push "$REGISTRY/$REPO/$NAME:$t"
done

PUSHED_DIGEST="$(docker inspect --format='{{index .RepoDigests 0}}' "$FIRST_REF" | sed 's/^.*@//')"
echo "Published $NAME:${TAGS[0]} digest: $PUSHED_DIGEST"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "### Published \`$NAME\`"
    echo ""
    echo "- Tags: ${TAGS[*]}"
    echo "- Digest: \`$PUSHED_DIGEST\`"
    echo "- Revision label: \`$GIT_COMMIT\`"
    if [ -n "$BASE_REF" ]; then
      if [ "$BASE_FRESH" = "true" ]; then
        echo "- Built FROM: \`$BASE_REF\` (resolved live this run)"
      else
        echo "- Built FROM: \`$BASE_REF\` (base unchanged this run; digest resolved live from its published tag)"
      fi
    fi
    echo ""
  } >> "$GITHUB_STEP_SUMMARY"
fi
