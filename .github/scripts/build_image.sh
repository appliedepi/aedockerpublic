#!/bin/bash
# Build (and, in "publish" mode, push) ONE image from the CI plan, resolving
# its base image (if any) by re-querying the registry LIVE for the base's
# digest -- from the image it just pushed if the base was ALSO rebuilt this
# run, else from the base's published (unchanged) tag. base_digest in
# images.yaml is now only an OPTIONAL cross-check, never required (see the
# base-resolution block below and images.yaml's base_digest field comment).
#
# Usage:
#   build_image.sh <mode> <repo_lowercased> <name> <dir> <tags_csv> \
#                   <base_name> <base_tag> <base_digest> <base_freshly_built> \
#                   <git_commit> <context>
# (base_name/base_tag/base_digest are empty strings, and base_freshly_built
# is "false", for an image with no base, e.g. rbase itself. <context>
# defaults to <dir> when omitted -- see CONTEXT below.)
#
# <mode> is "publish" or "verify":
#   publish -- build.yml / the real publish path. Tags as
#     $REGISTRY/<repo>/<name>:<tag> for EVERY tag and PUSHES every tag.
#     Requires a prior `docker login` to $REGISTRY. A freshly-built base is
#     re-resolved from the REGISTRY (it was pushed earlier in this run,
#     possibly by a different job/runner -- see images.yaml's digest-pinning
#     procedure).
#   verify -- a drift-detection / local dry-run path. Builds the exact same
#     Dockerfile with the exact same base-resolution RULES, but never
#     pushes: a freshly-built base is referenced by its plain LOCAL tag (no
#     registry round-trip), and the image being built here is tagged
#     WITHOUT the registry prefix (it is never going to be pushed, so it
#     never gets a real registry name). No registry AUTH is needed at all
#     in this mode -- a pull of a PUBLISHED base (the not-freshly-built
#     branch) is a read of a PUBLIC image, which needs none. Nothing in
#     this repo schedules "verify" automatically; it remains available for
#     a human to run by hand (e.g. PROJECT.md's local-registry rehearsal).
#
# GIT_COMMIT (the CI's per-image change-detection anchor): stamped onto the
# built image as the org.opencontainers.image.revision LABEL, alongside
# org.opencontainers.image.source (derived from REPO as
# "https://github.com/$REPO"). This is what the NEXT run's
# .github/scripts/changed_images.py reads back (via a metadata-only
# `docker buildx imagetools inspect`, never a `docker pull`) to decide
# whether THIS image needs rebuilding: never-published, or no revision
# label -> changed; otherwise a `git diff` of this image's own dir + the
# shared build inputs + .github/ machinery, since exactly this commit. This
# is what makes an ordinary content-change rebuild and a clean resume of a
# partial publish the SAME mechanism -- see changed_images.py's own header.
# A missing/empty GIT_COMMIT is a hard error (below): a build that silently
# stamped an empty revision would make changed_images.py treat this image
# as changed FOREVER, on every future run, with no visible symptom until
# someone notices the excess rebuilding.
#
# REGISTRY defaults to ghcr.io; overridable via the environment for local
# testing against a throwaway registry (e.g. REGISTRY=localhost:5000) --
# see PROJECT.md for the base_digest-agreement simulation this enables.
#
# GITHUB_PAT is OPTIONAL and, when set, is passed to `docker build` as a
# BuildKit secret (--secret id=github_pat,env=GITHUB_PAT), NEVER as
# --build-arg: a build-arg lands in `docker history` even if it is never
# promoted to an ENV, which is exactly the leak this project's own hard rule
# forbids (see PROJECT.md section 4 / the Dockerfile's own comment on this).
# It exists ONLY to raise pak's GitHub API rate limit while resolving the
# GitHub-SHA-pinned packages in epirhandbook's build -- a repo-CONTENTS
# read, nothing more -- so the caller (build.yml) must source it from a
# credential scoped to PUBLIC READ ONLY (this project's `GH_READONLY_PAT`
# repository secret), NEVER from a token that also holds `packages: write`
# (Phase 4 round 2 blocker: arbitrary package-build code for 473 packages,
# several of them compiled from source with their own post-install scripts,
# must never run with a registry-push-capable credential). If GITHUB_PAT is
# unset or empty, this script builds with NO token at all -- it never
# substitutes a different, more-privileged credential on its own; the build
# then simply relies on the ANONYMOUS GitHub API rate limit for those GitHub
# lookups (fine in normal operation; see PROJECT.md for the documented
# consequence on a shared runner IP).
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
BASE_NAME="$5"; BASE_TAG="$6"; BASE_DIGEST="$7"; BASE_FRESH="$8"
GIT_COMMIT="$9"
if [ -z "$GIT_COMMIT" ]; then
  echo "::error::build_image.sh: no git commit given (arg 9) -- every build must stamp org.opencontainers.image.revision, or changed_images.py can never resolve this image's last-published commit and will treat it as changed on every future run." >&2
  exit 1
fi
# The docker build CONTEXT. Defaults to DIR (rbase, the 2.5 monolith: the
# Dockerfile sits in the same directory its COPY paths resolve against). The
# 2.6/2.7 split images pass a different one: their Dockerfile lives in
# chapters/<ch>/ but COPYs renv.lock / pak_install_subset.R from
# epirhandbook/2.6 or 2.7, so the context must be that shared root while DIR
# stays per-chapter (change-detection scope). Building a chapter with its
# own dir as context fails -- the COPY sources are outside it.
CONTEXT="${10:-$DIR}"

IFS=',' read -r -a TAGS <<< "$TAGS_CSV"

BUILD_ARGS=()

# Date-stamped tag -> CRAN_SNAPSHOT_DATE build-arg. If the first tag ends in a
# literal YYYY-MM-DD (rbase's "4.6.0-2026-07-01"), that date IS the single
# source of truth for the pinned CRAN snapshot: extract it and pass it so the
# Dockerfile derives the snapshot URL from it (rbase/4.6.0/Dockerfile). The
# rule is generic, not rbase-specific: a tag with no date suffix (a chapter's
# "2.7") simply does not match, so no arg is passed and no Dockerfile consumes
# one. One date, defined once, in the tag.
if [[ "${TAGS[0]}" =~ -([0-9]{4}-[0-9]{2}-[0-9]{2})$ ]]; then
  BUILD_ARGS+=(--build-arg "CRAN_SNAPSHOT_DATE=${BASH_REMATCH[1]}")
  echo "$NAME: tag '${TAGS[0]}' carries snapshot date ${BASH_REMATCH[1]} -> passing as --build-arg CRAN_SNAPSHOT_DATE"
fi

BASE_REF=""
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
    else
      # verify mode: the base was built earlier in THIS SAME job, on THIS
      # SAME runner -- reference it by its plain local tag directly. There
      # is no push, so there is no registry digest to re-resolve.
      BASE_REF="$BASE_NAME:$BASE_TAG"
      echo "Using the LOCAL image built earlier in this run: $BASE_REF (verify mode never pushes, so there is no registry digest to re-resolve)"
    fi
  else
    # The base was NOT rebuilt in this run. Under the OCI-revision change model
    # that means the base is UNCHANGED since its last publish and already in
    # the registry, so its current published tag IS the correct base to build
    # FROM -- resolve its digest LIVE. This is what makes a partial-publish
    # RESUME clean: on a rerun the unchanged base is skipped (not rebuilt this
    # run), but its dependent must still build against the published base, and
    # on a FIRST publish there is no recorded base_digest yet (base_digest:
    # null). A pure registry READ (imagetools inspect) -- never a docker pull,
    # no auth for a public image.
    REG_TAG="$REGISTRY/$REPO/$BASE_NAME:$BASE_TAG"
    echo "Resolving $BASE_NAME's digest live from $REGISTRY (not rebuilt this run; unchanged since last publish): $REG_TAG"
    LIVE_DIGEST="$(docker buildx imagetools inspect "$REG_TAG" | awk '/^Digest:/{print $2; exit}')"
    if [ -z "$LIVE_DIGEST" ]; then
      echo "::error::'$BASE_NAME' was not rebuilt this run and its tag $REG_TAG does not resolve in the registry -- the base has never been published, so '$NAME' has nothing to build FROM. The layered plan builds a base before its dependents, so this should not happen in a normal run." >&2
      exit 1
    fi
    # A recorded base_digest, when present, is an OPTIONAL cross-check that the
    # base has not moved out from under it. When absent (null -- the
    # first-publish / resume case) the live digest is used directly. This does
    # NOT silently follow drift: under the OCI-revision model a base that
    # actually changed would be in THIS run's plan (BASE_FRESH=true, resolved
    # in the branch above), so a BASE_FRESH=false base is unchanged by
    # construction and its live tag is the right one.
    if [ -n "$BASE_DIGEST" ] && [ "$BASE_DIGEST" != "null" ] && [ "$BASE_DIGEST" != "$LIVE_DIGEST" ]; then
      echo "::error::Recorded base_digest for '$BASE_NAME' ($BASE_DIGEST) does not match what $REG_TAG currently resolves to ($LIVE_DIGEST) -- the base moved since the pin was recorded. Update or clear the base_digest for '$NAME' and commit." >&2
      exit 1
    fi
    DIGEST="$LIVE_DIGEST"
    echo "$NAME will build FROM the published $BASE_NAME at digest $DIGEST"
    BASE_REF="$REGISTRY/$REPO/$BASE_NAME@$DIGEST"
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

# org.opencontainers.image.revision/.source -- see the header comment above.
# REPO_URL is derived from REPO (already the lowercased owner/repo used for
# every registry ref in this script) rather than threaded through as a
# separate argument -- one fewer positional to keep in sync, and GitHub
# repository URLs resolve case-insensitively regardless.
REPO_URL="https://github.com/$REPO"
LABEL_ARGS=(
  --label "org.opencontainers.image.revision=$GIT_COMMIT"
  --label "org.opencontainers.image.source=$REPO_URL"
)

echo "Building $NAME from $DIR (context: $CONTEXT) with tags: ${TAGS[*]} (mode: $MODE)"
echo "Stamping org.opencontainers.image.revision=$GIT_COMMIT, org.opencontainers.image.source=$REPO_URL"
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
    echo "If other images pin their base to \`$NAME\`, update their \`base_digest\` in \`images.yaml\` to \`$PUSHED_DIGEST\` and commit."
    echo ""
  } >> "$GITHUB_STEP_SUMMARY"
fi
