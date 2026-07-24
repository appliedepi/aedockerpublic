#!/usr/bin/env python3
"""Unit tests for changed_images.py.

Two things are tested, deliberately differently:
  - changed_since() -- against a REAL, synthetic, throwaway git repo (not a
    mocked one), so this proves the actual `git diff --name-only <rev>
    <sha>` invocation behaves as documented, including the "single diff
    between two snapshots, never per-commit" invariant.
  - files_touch_image() -- against a synthetic changed-file list (no git
    needed for this half), mirroring test_plan.py's own style of testing
    build_plan()'s selection logic directly.

published_revision() (the registry-querying half, which shells out to
`docker buildx imagetools inspect`) is NOT unit-mocked here -- mocking the
registry call would only prove the mock agrees with itself, not that the
real invocation actually extracts the label from a real registry. That
half is integration-tested by running this helper for real in CI, not
unit-mocked (see the brief this module implements).

Run directly:
    python3 .github/scripts/test_changed_images.py -v
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import changed_images  # noqa: E402


def _git(repo, *args):
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


class TestChangedSinceAgainstSyntheticRepo(unittest.TestCase):
    """changed_since() against a REAL git history in a throwaway repo --
    this repo is created fresh per test and never touches global git
    config (only ever `git -C <tmpdir> config ...`, scoped to that one
    throwaway repo's own .git/config)."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="changed-images-test-")
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "test@example.invalid")
        _git(self.repo, "config", "user.name", "Test")

    def _commit(self, relpath, content):
        full = os.path.join(self.repo, relpath)
        parent = os.path.dirname(full)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        _git(self.repo, "add", relpath)
        _git(self.repo, "commit", "-q", "-m", f"write {relpath}={content}")
        return _git(self.repo, "rev-parse", "HEAD").strip()

    def test_file_changed_after_revision_is_reported(self):
        rev1 = self._commit("a/file.txt", "v1")
        rev2 = self._commit("b/other.txt", "v1")
        changed = changed_images.changed_since(rev1, rev2, cwd=self.repo)
        self.assertEqual(changed, ["b/other.txt"])

    def test_no_changes_since_revision_is_empty(self):
        rev = self._commit("a/file.txt", "v1")
        changed = changed_images.changed_since(rev, rev, cwd=self.repo)
        self.assertEqual(changed, [])

    def test_multiple_intermediate_commits_flatten_into_one_diff(self):
        # A push containing several commits must produce exactly one
        # comparison of final states, not one entry per intermediate
        # commit -- git diff between two snapshots already has this
        # property; this test pins it so a future refactor (e.g. an
        # accidental switch to a per-commit `git log`-driven loop) would
        # break it visibly.
        rev1 = self._commit("a/file.txt", "v1")
        self._commit("a/file.txt", "v2")  # intermediate commit
        rev3 = self._commit("c/new.txt", "v1")  # another intermediate commit
        changed = changed_images.changed_since(rev1, rev3, cwd=self.repo)
        self.assertEqual(set(changed), {"a/file.txt", "c/new.txt"})

    def test_change_then_revert_within_the_same_span_nets_to_no_diff(self):
        # The exact scenario called out by name: a file changed and then
        # reverted back to its original content across several commits
        # between `revision` and `sha` must NOT appear in the diff --
        # `git diff` compares tree snapshots, so identical content at both
        # ends means no difference, regardless of what happened in between.
        rev1 = self._commit("a/file.txt", "v1")
        self._commit("a/file.txt", "v2")
        rev3 = self._commit("a/file.txt", "v1")  # reverted back to v1
        changed = changed_images.changed_since(rev1, rev3, cwd=self.repo)
        self.assertEqual(changed, [])

    def test_unresolvable_revision_raises(self):
        self._commit("a/file.txt", "v1")
        with self.assertRaises(RuntimeError):
            changed_images.changed_since("0" * 40, "HEAD", cwd=self.repo)


class TestFilesTouchImage(unittest.TestCase):
    """files_touch_image()'s matching rules, given an already-known
    changed-file list (no git or registry involved)."""

    COMMON = {"name": "epirhandbook-common", "dir": "epirhandbook/2.7/common",
              "context": "epirhandbook/2.7"}
    BASICS = {"name": "epirhandbook-basics", "dir": "epirhandbook/2.7/chapters/basics",
              "context": "epirhandbook/2.7"}
    CLEANING = {"name": "epirhandbook-cleaning", "dir": "epirhandbook/2.7/chapters/cleaning",
                "context": "epirhandbook/2.7"}
    ALL_DIRS = [COMMON["dir"], BASICS["dir"], CLEANING["dir"]]

    def test_own_dir_change_touches(self):
        touched, _ = changed_images.files_touch_image(
            self.BASICS, ["epirhandbook/2.7/chapters/basics/Dockerfile"], self.ALL_DIRS)
        self.assertTrue(touched)

    def test_sibling_dir_change_does_not_touch(self):
        # A file under CLEANING's own dir must not touch BASICS -- else
        # per-chapter selectivity would be lost entirely.
        touched, _ = changed_images.files_touch_image(
            self.BASICS, ["epirhandbook/2.7/chapters/cleaning/Dockerfile"], self.ALL_DIRS)
        self.assertFalse(touched)

    def test_shared_context_input_touches_every_image_sharing_that_context(self):
        # renv.lock-equivalent sitting at the context root, outside every
        # image's own dir -- touches common AND every chapter.
        for img in (self.COMMON, self.BASICS, self.CLEANING):
            touched, _ = changed_images.files_touch_image(
                img, ["epirhandbook/2.7/pak_install_subset.R"], self.ALL_DIRS)
            self.assertTrue(touched, msg=f"{img['name']} should see the shared context input")

    def test_ci_machinery_change_touches_every_image(self):
        for img in (self.COMMON, self.BASICS, self.CLEANING):
            touched, _ = changed_images.files_touch_image(
                img, [".github/scripts/build_image.sh"], self.ALL_DIRS)
            self.assertTrue(touched)
            touched, _ = changed_images.files_touch_image(
                img, [".github/workflows/build.yml"], self.ALL_DIRS)
            self.assertTrue(touched)

    def test_unrelated_workflow_adjacent_file_is_not_machinery(self):
        # .github/CODEOWNERS is NOT in MACHINERY_DIRS (.github/scripts,
        # .github/workflows only) -- same scope the old is_special_trigger
        # used, deliberately not widened to all of .github/.
        touched, _ = changed_images.files_touch_image(
            self.BASICS, [".github/CODEOWNERS"], self.ALL_DIRS)
        self.assertFalse(touched)

    def test_unrelated_file_does_not_touch(self):
        touched, _ = changed_images.files_touch_image(
            self.BASICS, ["README.md"], self.ALL_DIRS)
        self.assertFalse(touched)

    def test_no_context_field_defaults_to_dir_and_still_matches_own_dir(self):
        rbase = {"name": "rbase", "dir": "rbase/4.6.0"}
        touched, _ = changed_images.files_touch_image(
            rbase, ["rbase/4.6.0/Dockerfile"], ["rbase/4.6.0"])
        self.assertTrue(touched)

    def test_sibling_directory_prefix_does_not_false_match(self):
        # rbase/4.6.0-other/... must NOT match dir "rbase/4.6.0" -- pins
        # plan.matching_dir's own sibling-prefix-collision protection,
        # which files_touch_image relies on directly.
        rbase = {"name": "rbase", "dir": "rbase/4.6.0"}
        touched, _ = changed_images.files_touch_image(
            rbase, ["rbase/4.6.0-other/x.txt"], ["rbase/4.6.0"])
        self.assertFalse(touched)

    def test_multiple_changed_files_union_correctly(self):
        # A changed-file list can touch an image via ANY entry, not just
        # the first.
        touched, _ = changed_images.files_touch_image(
            self.BASICS,
            ["README.md", "epirhandbook/2.7/chapters/cleaning/x", "epirhandbook/2.7/chapters/basics/y"],
            self.ALL_DIRS,
        )
        self.assertTrue(touched)


class TestImageIsChanged(unittest.TestCase):
    """image_is_changed()'s never-published branch -- the registry read
    itself is not mocked (see module docstring), but published_revision()
    returning None (which is exactly what it returns for a ref that does
    not exist, since no registry is reachable in this test environment)
    exercises the real "never-published = changed" path end to end."""

    def test_unpublished_image_is_always_changed(self):
        img = {"name": "definitely-never-published-anywhere",
               "dir": "nowhere", "tags": ["1"]}
        changed, reason = changed_images.image_is_changed(
            img, "ghcr.io", "appliedepi/aedockerpublic-test-nonexistent",
            "HEAD", ["nowhere"], {},
        )
        self.assertTrue(changed)
        self.assertIn("never-published", reason)


if __name__ == "__main__":
    unittest.main()
