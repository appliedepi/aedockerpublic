#!/bin/bash
# Build (and, in "publish" mode, push) ONE image from the CI plan, resolving
# its base image (if any) either by re-querying the registry live (base was
# ALSO rebuilt earlier in this same run) or by using the base_digest pin
# recorded in images.yaml (base was not rebuilt this run). See images.yaml's
# "Digest-pinning procedure" comment for why this split is the
# chicken-and-egg fix, and PROJECT.md / the Phase 4 brief for why the base
# must be pinned by digest at all.
#
# Usage:
#   build_image.sh <mode> <repo_lowercased> <name> <dir> <tags_csv> \
#                   <base_name> <base_tag> <base_digest> <base_freshly_built> \
#                   <frozen>
#   build_image.sh check-frozen <repo_lowercased> <name> <tags_csv> <frozen>
# (base_name/base_tag/base_digest are empty strings, and base_freshly_built
# is "false", for an image with no base, e.g. rbase itself.)
#
# <mode> is "publish", "verify", or "check-frozen":
#   publish -- build.yml / the real publish path. Tags as
#     $REGISTRY/<repo>/<name>:<tag> for EVERY tag and PUSHES every tag.
#     Requires a prior `docker login` to $REGISTRY. A freshly-built base is
#     re-resolved from the REGISTRY (it was pushed earlier in this run,
#     possibly by a different job/runner -- see images.yaml's digest-pinning
#     procedure).
#   verify -- nightly.yml / the drift-detection path. Builds the exact same
#     Dockerfile with the exact same base-resolution RULES, but never
#     pushes: a freshly-built base is referenced by its plain LOCAL tag (no
#     registry round-trip -- nightly runs the whole cascade in one job on
#     one runner, so the base built a moment ago is already on this
#     runner's own Docker daemon), and the image being built here is
#     tagged WITHOUT the registry prefix (it is never going to be pushed,
#     so it never gets a real registry name). nightly.yml holds no
#     `packages: write` and never calls docker/login-action, so "verify"
#     must not need registry AUTH at all -- a pull of a PUBLISHED base (the
#     not-freshly-built branch) is a read of a PUBLIC image, which needs
#     none.
#   check-frozen -- a fast, standalone frozen-tag check with NO docker build
#     and NO docker login involved at all (Phase 4 round 2 remediation:
#     "move the frozen check before docker build and before the registry
#     login"). build.yml now runs this as its OWN step, before
#     docker/login-action, so a doomed republish attempt never spends the
#     ~45-minute compile AND never even exchanges the registry-push
#     credential into the runner's Docker config -- both of which used to
#     happen before the refusal was ever detected. Exits 0 (proceed) or 1
#     (refuse) with the exact same logic `publish` mode itself applies (see
#     check_frozen_or_die below) -- kept in BOTH places, not moved
#     out of `publish` entirely, so build_image.sh remains self-contained:
#     a human invoking it directly in `publish` mode (as PROJECT.md's local
#     registry rehearsal does) still gets the refusal even without going
#     through build.yml's own step ordering first. images.yaml's `frozen:`
#     field comment documents this as something "build_image.sh enforces...
#     in publish mode" -- WHEN inside publish mode the refusal runs is not
#     part of that contract, only THAT it runs before any tag is pushed.
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
# It exists ONLY to raise pak's GitHub API rate limit while resolving the 7
# GitHub-SHA-pinned packages in epirhandbook's build -- a repo-CONTENTS
# read, nothing more -- so the caller (build.yml / nightly.yml) must source
# it from a credential scoped to PUBLIC READ ONLY (this project's
# `GH_READONLY_PAT` repository secret), NEVER from a token that also holds
# `packages: write` (Phase 4 round 2 blocker: arbitrary package-build code
# for 473 packages, several of them compiled from source with their own
# post-install scripts, must never run with a registry-push-capable
# credential). If GITHUB_PAT is unset or empty, this script builds with NO
# token at all -- it never substitutes a different, more-privileged
# credential on its own; the build then simply relies on the ANONYMOUS
# GitHub API rate limit for those 7 lookups (fine in normal operation; see
# PROJECT.md for the documented consequence on a shared runner IP).
#
# FORCE_REPUBLISH_FROZEN (publish and check-frozen modes only): a
# comma-separated list of image NAMES (matching images.yaml's `name:`
# field) allowed to republish over an already-published tag even though
# `frozen: true`. Empty by default. Sourced from build.yml's
# workflow_dispatch input of the same name -- a deliberate, explicit,
# human-supplied override, never set by automation. See
# check_frozen_or_die below and images.yaml's `frozen:` field comment.
set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io}"
FORCE_REPUBLISH_FROZEN="${FORCE_REPUBLISH_FROZEN:-}"

MODE="$1"; shift
case "$MODE" in
  publish|verify|check-frozen) ;;
  *)
    echo "::error::build_image.sh: unknown mode '$MODE' (expected 'publish', 'verify', or 'check-frozen')" >&2
    exit 1
    ;;
esac

# --- Frozen-tag refusal (blocker 2 / images.yaml's `frozen:` field) ---------
# A frozen image is published once, deliberately, and never republished on a
# schedule or by accident. Before pushing ANY tag, refuse if this image is
# frozen AND at least one of its tags already exists in the registry --
# UNLESS this image's name is explicitly listed in FORCE_REPUBLISH_FROZEN (a
# human, dispatching build.yml by hand, saying "yes, really replace the
# frozen artifact"). Checked for every tag BEFORE pushing any of them, so a
# multi-tag image never ends up partially republished.
#
# A pure registry READ (imagetools inspect) -- no auth needed for a public
# image (same assumption the base_digest check below already relies on), so
# it is safe to run standalone, before docker/login-action ever runs.
check_frozen_or_die() {
  local repo="$1" name="$2" tags_csv="$3" frozen="$4"
  if [ "$frozen" != "true" ]; then
    return 0
  fi
  local overridden="false"
  case ",$FORCE_REPUBLISH_FROZEN," in
    *",$name,"*) overridden="true" ;;
  esac
  if [ "$overridden" = "true" ]; then
    echo "'$name' is frozen, but was explicitly listed in FORCE_REPUBLISH_FROZEN -- proceeding with the republish."
    return 0
  fi
  local t check_ref _tags
  IFS=',' read -r -a _tags <<< "$tags_csv"
  for t in "${_tags[@]}"; do
    check_ref="$REGISTRY/$repo/$name:$t"
    if docker buildx imagetools inspect "$check_ref" >/dev/null 2>&1; then
      echo "::error::'$name' is frozen: true in images.yaml, and $check_ref already exists in the registry. A frozen image is published once, deliberately, and never republished automatically. If this is a genuine, deliberate republish, re-run build.yml via workflow_dispatch with force_republish_frozen including '$name'." >&2
      exit 1
    fi
  done
  echo "'$name' is frozen, but none of its tags exist in the registry yet (first publish) -- proceeding."
}

if [ "$MODE" = "check-frozen" ]; then
  REPO="$1"; NAME="$2"; TAGS_CSV="$3"; FROZEN="${4:-false}"
  check_frozen_or_die "$REPO" "$NAME" "$TAGS_CSV" "$FROZEN"
  exit 0
fi

REPO="$1"; NAME="$2"; DIR="$3"; TAGS_CSV="$4"
BASE_NAME="$5"; BASE_TAG="$6"; BASE_DIGEST="$7"; BASE_FRESH="$8"
FROZEN="${9:-false}"
# The docker build CONTEXT. Defaults to DIR (rbase, the 2.5 monolith: the
# Dockerfile sits in the same directory its COPY paths resolve against). The
# 2.6 split images pass a different one: their Dockerfile lives in
# chapters/<ch>/ but COPYs renv.lock / pak_install_subset.R from
# epirhandbook/2.6/, so the context must be 2.6/ while DIR stays per-chapter
# (change-detection scope). Building a chapter with its own dir as context
# fails -- the COPY sources are outside it.
CONTEXT="${10:-$DIR}"

# Re-run the SAME check inline, before base resolution and long before
# `docker build`, so a direct `publish`-mode invocation (e.g. PROJECT.md's
# local-registry rehearsal) refuses just as fast as build.yml's own
# check-frozen step does -- see the header comment on why this is not
# removed from `publish` even though build.yml now also checks earlier.
if [ "$MODE" = "publish" ]; then
  check_frozen_or_die "$REPO" "$NAME" "$TAGS_CSV" "$FROZEN"
fi

IFS=',' read -r -a TAGS <<< "$TAGS_CSV"

BUILD_ARGS=()
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
    if [ -z "$BASE_DIGEST" ] || [ "$BASE_DIGEST" = "null" ]; then
      echo "::error::No base_digest recorded in images.yaml for '$NAME', and '$BASE_NAME' was not rebuilt in this run -- there is nothing to pin against. See images.yaml's digest-pinning procedure (a human must record a base_digest after $BASE_NAME's first publish)." >&2
      exit 1
    fi
    # Steady-state pin. BEFORE trusting the recorded base_digest, confirm
    # it still agrees with what the base's FLOATING tag currently resolves
    # to in the registry -- finding 5. Without this, a base that moved
    # (someone force-pushed over rbase:4.3.2, or re-ran a bootstrap build)
    # silently gets built against a STALE recorded pin instead: the build
    # would "succeed" against an image that is no longer the one actually
    # published under that tag, and nothing would say so. This check is a
    # pure registry READ (imagetools inspect), so it costs nothing extra in
    # either mode and needs no auth for a public image.
    REG_TAG="$REGISTRY/$REPO/$BASE_NAME:$BASE_TAG"
    echo "Checking the recorded base_digest pin for $BASE_NAME against what $REG_TAG currently resolves to..."
    LIVE_DIGEST="$(docker buildx imagetools inspect "$REG_TAG" | awk '/^Digest:/{print $2; exit}')"
    if [ -z "$LIVE_DIGEST" ]; then
      echo "::error::Could not resolve a digest for $REG_TAG via 'docker buildx imagetools inspect' -- has it ever been published?" >&2
      exit 1
    fi
    if [ "$LIVE_DIGEST" != "$BASE_DIGEST" ]; then
      echo "::error::Stale base_digest for '$BASE_NAME' in images.yaml: recorded $BASE_DIGEST, but $REG_TAG currently resolves to $LIVE_DIGEST. '$BASE_NAME' moved since this pin was recorded. Update images.yaml's base_digest for '$NAME' to $LIVE_DIGEST (after confirming the new $BASE_NAME is good) and commit." >&2
      exit 1
    fi
    DIGEST="$BASE_DIGEST"
    echo "Recorded base_digest pin for $BASE_NAME confirmed current: $DIGEST"
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

echo "Building $NAME from $DIR (context: $CONTEXT) with tags: ${TAGS[*]} (mode: $MODE)"
if [ -n "${GITHUB_PAT:-}" ]; then
  echo "GITHUB_PAT is set (a read-only credential, or an operator-supplied token for local testing) -- passing it as a BuildKit secret."
else
  echo "GITHUB_PAT is NOT set -- building with no GitHub token at all. pak's github:: package resolution falls back to the ANONYMOUS GitHub API rate limit for this build's 7 GitHub-pinned packages (see this script's header comment)."
fi
DOCKER_BUILDKIT=1 docker build \
  --secret id=github_pat,env=GITHUB_PAT \
  "${BUILD_ARGS[@]}" \
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
# (the frozen-tag refusal already ran above, before base resolution and
# `docker build` -- nothing left to check here, only to push)

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
    if [ -n "$BASE_REF" ]; then
      if [ "$BASE_FRESH" = "true" ]; then
        echo "- Built FROM: \`$BASE_REF\` (resolved live this run)"
      else
        echo "- Built FROM: \`$BASE_REF\` (recorded base_digest pin from images.yaml, confirmed current)"
      fi
    fi
    echo ""
    echo "If other images pin their base to \`$NAME\`, update their \`base_digest\` in \`images.yaml\` to \`$PUSHED_DIGEST\` and commit."
    echo ""
  } >> "$GITHUB_STEP_SUMMARY"
fi
