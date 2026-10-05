#!/usr/bin/env python3
"""Unit tests for changed_images.py.

The tests use two different methods:
  - changed_since() runs against a real git repo, created for the test and
    then deleted. It is not a mock. So the tests show that the real
    `git diff --name-only <rev> <sha>` call works as documented. That
    includes the rule "one diff between two snapshots, never one per
    commit".
  - files_touch_image() runs against a synthetic list of changed files,
    with no git. This is the same method that test_plan.py uses to test
    the selection logic of build_plan().

This file does not mock published_labels() or published_digest(). They
query the registry with `docker buildx imagetools inspect`. A mock of that
call would only show that the mock agrees with itself. It would not show
that the real call reads the label from a real registry. CI tests that
part when it runs this helper for real. This file does test
image_is_changed(), with dicts behind its `revision_of`, `labels_of` and
`digest_of` parameters. That tests the decision, not the registry read. No
test in this file uses the network or runs docker.

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

# repo root, for the "no Dockerfile COPYs a doc file" invariant below
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _git(repo, *args):
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


class TestChangedSinceAgainstSyntheticRepo(unittest.TestCase):
    """changed_since() against a real git history in a temporary repo. Each
    test creates a new repo. The tests never change the global git config.
    They only run `git -C <tmpdir> config ...`, which writes the
    .git/config of that temporary repo."""

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
        # A push with several commits MUST give one comparison of the final
        # states, not one entry per intermediate commit. git diff between
        # two snapshots already does this. This test pins it, so that a
        # future change to a per-commit loop driven by `git log` fails here.
        rev1 = self._commit("a/file.txt", "v1")
        self._commit("a/file.txt", "v2")  # intermediate commit
        rev3 = self._commit("c/new.txt", "v1")  # another intermediate commit
        changed = changed_images.changed_since(rev1, rev3, cwd=self.repo)
        self.assertEqual(set(changed), {"a/file.txt", "c/new.txt"})

    def test_change_then_revert_within_the_same_span_nets_to_no_diff(self):
        # A file changed and then reverted to its original content, across
        # several commits between `revision` and `sha`, MUST NOT appear in
        # the diff. `git diff` compares tree snapshots, so the same content
        # at both ends is no difference, whatever happened between them.
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
    """The matching rules of files_touch_image(), given a known list of
    changed files. The tests use no git and no registry."""

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
        # A file under the own dir of CLEANING MUST NOT touch BASICS.
        # Otherwise CI would lose the selection per chapter.
        touched, _ = changed_images.files_touch_image(
            self.BASICS, ["epirhandbook/2.7/chapters/cleaning/Dockerfile"], self.ALL_DIRS)
        self.assertFalse(touched)

    def test_shared_context_input_touches_every_image_sharing_that_context(self):
        # A file like renv.lock at the context root, outside the own dir of
        # every image. It touches common and every chapter.
        for img in (self.COMMON, self.BASICS, self.CLEANING):
            touched, _ = changed_images.files_touch_image(
                img, ["epirhandbook/2.7/pak_install_subset.R"], self.ALL_DIRS)
            self.assertTrue(touched, msg=f"{img['name']} should see the shared context input")

    def test_undeclared_context_file_touches_nothing(self):
        # A README, the change notes, a patch and five TSVs are beside the
        # real inputs at the context root. The old rule, "anything in the
        # context outside an image's dir", matched all of them. So a README
        # edit rebuilt 50 of 51 images. Now only SHARED_CONTEXT_INPUTS count.
        for undeclared in (
            "epirhandbook/2.7/README.md",
            "epirhandbook/2.7/CHANGES-2.6-to-2.7.md",
            "epirhandbook/2.7/BREAKAGE.tsv",
            "epirhandbook/2.7/forward-port.patch",
            "epirhandbook/2.7/footprints.tsv",
        ):
            for img in (self.COMMON, self.BASICS, self.CLEANING):
                touched, reason = changed_images.files_touch_image(
                    img, [undeclared], self.ALL_DIRS)
                self.assertFalse(
                    touched,
                    msg=f"{img['name']} should NOT rebuild for {undeclared} ({reason})")

    def test_declared_context_inputs_still_touch_every_sharing_image(self):
        # The other half: the allowlist MUST NOT weaken the rule for files
        # that are inputs.
        for declared in (
            "epirhandbook/2.7/pak_install_subset.R",
            "epirhandbook/2.7/packages_github.json",
            "epirhandbook/2.7/images.yaml",
        ):
            for img in (self.COMMON, self.BASICS, self.CLEANING):
                touched, _ = changed_images.files_touch_image(
                    img, [declared], self.ALL_DIRS)
                self.assertTrue(
                    touched, msg=f"{img['name']} must rebuild for {declared}")

    def test_undeclared_file_does_not_mask_a_later_real_input(self):
        # files_touch_image returns on the first match. An excluded file MUST
        # pass to the next file. It MUST NOT return False early and hide a
        # real input later in the same changeset.
        touched, reason = changed_images.files_touch_image(
            self.BASICS,
            ["epirhandbook/2.7/README.md", "epirhandbook/2.7/pak_install_subset.R"],
            self.ALL_DIRS)
        self.assertTrue(touched)
        self.assertIn("pak_install_subset.R", reason)

    def test_documentation_inside_an_image_own_dir_still_touches(self):
        # The allowlist applies only to the shared-context rule. A file in an
        # image's own dir rebuilds that one image. That costs little, and it
        # fails closed.
        touched, _ = changed_images.files_touch_image(
            self.BASICS, ["epirhandbook/2.7/chapters/basics/NOTES.md"], self.ALL_DIRS)
        self.assertTrue(touched)

    def test_every_copied_context_file_is_a_declared_input(self):
        # This invariant makes the allowlist safe. If a Dockerfile COPYs a
        # context-root file that SHARED_CONTEXT_INPUTS does not name, an edit
        # to that file does not rebuild. The image then goes stale with no
        # sign.
        #
        # The parser reads COPY and ADD, shell and JSON form, --flags, and
        # more than one source (every argument except the last is a source).
        # A regex for the first argument only would miss
        # `COPY pak_install_subset.R README.md /tmp/`.
        import glob
        import json as _json
        import re
        import yaml as _yaml

        def sources(line):
            m = re.match(r"\s*(COPY|ADD)\s+(.*)", line, re.I)
            if not m:
                return []
            rest = re.sub(r"--\S+\s*", "", m.group(2)).strip()
            if rest.startswith("["):
                try:
                    parts = _json.loads(rest)
                except ValueError:
                    return []
            else:
                parts = rest.split()
            return parts[:-1] if len(parts) > 1 else []

        catalog = []
        for cat in ("images.yaml", "epirhandbook/2.9/images.yaml"):
            with open(os.path.join(REPO_ROOT, cat), encoding="utf-8") as fh:
                catalog += _yaml.safe_load(fh)["images"]
        all_dirs = [i["dir"] for i in catalog]

        problems = []
        for img in catalog:
            ctx = img.get("context", img["dir"])
            df = os.path.join(REPO_ROOT, img["dir"], "Dockerfile")
            if not os.path.exists(df):
                continue
            with open(df, encoding="utf-8") as fh:
                lines = fh.readlines()
            for line in lines:
                for src in sources(line):
                    if src in (".", "./"):
                        problems.append(
                            f"{img['name']}: broad context copy `{line.strip()}` "
                            f"-- sweeps in every context file, including ones "
                            f"SHARED_CONTEXT_INPUTS does not track")
                        continue
                    repo_path = os.path.normpath(os.path.join(ctx, src))
                    inside_an_image_dir = any(
                        repo_path == d or repo_path.startswith(d + "/") for d in all_dirs)
                    if inside_an_image_dir:
                        continue
                    if not changed_images.is_shared_context_input(repo_path, ctx):
                        problems.append(
                            f"{img['name']}: COPYs `{src}` from the shared context, "
                            f"but it is not in SHARED_CONTEXT_INPUTS -- edits to it "
                            f"would not rebuild this image")
        self.assertEqual(problems, [], msg="\n".join(problems))

    def test_ci_machinery_change_touches_every_image(self):
        for img in (self.COMMON, self.BASICS, self.CLEANING):
            touched, _ = changed_images.files_touch_image(
                img, [".github/scripts/build_image.sh"], self.ALL_DIRS)
            self.assertTrue(touched)
            touched, _ = changed_images.files_touch_image(
                img, [".github/workflows/build.yml"], self.ALL_DIRS)
            self.assertTrue(touched)

    def test_unrelated_workflow_adjacent_file_is_not_machinery(self):
        # .github/CODEOWNERS is not in MACHINERY_DIRS, which holds only
        # .github/scripts and .github/workflows. That is the scope the old
        # is_special_trigger used. It does not cover all of .github/.
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
        # rbase/4.6.0-other/... MUST NOT match dir "rbase/4.6.0". This pins
        # the guard in plan.matching_dir against a sibling with the same
        # prefix. files_touch_image uses that guard directly.
        rbase = {"name": "rbase", "dir": "rbase/4.6.0"}
        touched, _ = changed_images.files_touch_image(
            rbase, ["rbase/4.6.0-other/x.txt"], ["rbase/4.6.0"])
        self.assertFalse(touched)

    def test_multiple_changed_files_union_correctly(self):
        # Any entry of a changed-file list can touch an image, not only the
        # first.
        touched, _ = changed_images.files_touch_image(
            self.BASICS,
            ["README.md", "epirhandbook/2.7/chapters/cleaning/x", "epirhandbook/2.7/chapters/basics/y"],
            self.ALL_DIRS,
        )
        self.assertTrue(touched)


class TestImageIsChanged(unittest.TestCase):
    """The never-published branch of image_is_changed().
    published_revision() returns None for an image that is not published,
    has no revision label, or cannot be read. The lookup here returns that
    None directly."""

    def test_unpublished_image_is_always_changed(self):
        img = {"name": "definitely-never-published-anywhere",
               "dir": "nowhere", "tags": ["1"]}

        def must_not_run(*args):
            raise AssertionError(f"unexpected lookup {args}: an unpublished image needs none")

        changed, reason = changed_images.image_is_changed(
            img, "ghcr.io", "appliedepi/aedockerpublic-test-nonexistent",
            "HEAD", ["nowhere"], {},
            revision_of=lambda registry, repo, name, tag: None,
            labels_of=must_not_run, digest_of=must_not_run,
        )
        self.assertTrue(changed)
        self.assertIn("never-published", reason)


class TestBaseDigest(unittest.TestCase):
    """The base-digest rule of image_is_changed(). Dicts replace both
    registry reads, so there is no network and no docker.

    The rule exists for this case. common publishes at commit S, and a group
    image fails to publish. A rerun finds common unchanged, because its label
    is S. It also finds the group unchanged, because its own diff is empty: a
    change under common's dir is not one of the group's files. Only the
    group's org.opencontainers.image.base.digest label shows that it was
    built FROM the old common."""

    REGISTRY = "ghcr.io"
    REPO = "appliedepi/aedockerpublic"
    OLD = "1" * 40  # the group's published revision, from before the failed run
    S = "5" * 40    # the revision common published at
    D_OLD = "sha256:" + "a" * 64
    D_NEW = "sha256:" + "b" * 64

    COMMON = {"name": "epirhandbook-common", "dir": "epirhandbook/2.9/common",
              "context": "epirhandbook/2.9", "tags": ["2.9"],
              "base": "rbase:4.6.0-2026-07-01", "live": True}
    GROUP = {"name": "epirhandbook-analysis", "dir": "epirhandbook/2.9/groups/analysis",
             "context": "epirhandbook/2.9", "tags": ["2.9"],
             "base": "epirhandbook-common:2.9", "live": True}
    RBASE = {"name": "rbase", "dir": "rbase/4.6.0", "tags": ["4.6.0-2026-07-01"],
             "base": None, "live": True}
    ALL_DIRS = [COMMON["dir"], GROUP["dir"], RBASE["dir"]]

    def _run(self, img, labels, digests, diff_cache):
        """image_is_changed() with `labels` ({name: labels dict}) and `digests`
        ({(name, tag): digest}) behind the three registry reads. The revision
        is the REVISION_LABEL entry of `labels`. Records every digest read in
        self.digest_reads."""
        self.digest_reads = []

        def revision_of(registry, repo, name, tag):
            self.assertEqual((registry, repo), (self.REGISTRY, self.REPO))
            return (labels.get(name) or {}).get(changed_images.REVISION_LABEL)

        def labels_of(registry, repo, name, tag):
            self.assertEqual((registry, repo), (self.REGISTRY, self.REPO))
            return labels.get(name)

        def digest_of(registry, repo, name, tag):
            self.assertEqual((registry, repo), (self.REGISTRY, self.REPO))
            self.digest_reads.append((name, tag))
            return digests.get((name, tag))

        return changed_images.image_is_changed(
            img, self.REGISTRY, self.REPO, "SHA", self.ALL_DIRS, diff_cache,
            revision_of=revision_of, labels_of=labels_of, digest_of=digest_of,
        )

    def _labels(self, revision, base_digest=None):
        labels = {changed_images.REVISION_LABEL: revision}
        if base_digest is not None:
            labels[changed_images.BASE_DIGEST_LABEL] = base_digest
        return labels

    def test_base_digest_differs_from_label_is_changed(self):
        # The partial publish: common moved on, the group did not publish,
        # and the group's own files did not change since its revision.
        diff = ["epirhandbook/2.9/common/Dockerfile"]
        touched, _ = changed_images.files_touch_image(self.GROUP, diff, self.ALL_DIRS)
        self.assertFalse(touched, msg="the own-file rule alone must miss this case")
        changed, reason = self._run(
            self.GROUP,
            labels={"epirhandbook-analysis": self._labels(self.OLD, self.D_OLD)},
            digests={("epirhandbook-common", "2.9"): self.D_NEW},
            diff_cache={self.OLD: diff},
        )
        self.assertTrue(changed, msg=reason)
        self.assertIn("epirhandbook-common:2.9", reason)
        self.assertIn(self.D_OLD, reason)
        self.assertIn(self.D_NEW, reason)

    def test_base_republished_at_same_revision_is_changed(self):
        # Base and group both carry revision S, so no commit comparison sees
        # anything. The base was republished at S with a new digest.
        changed, reason = self._run(
            self.GROUP,
            labels={"epirhandbook-analysis": self._labels(self.S, self.D_OLD),
                    "epirhandbook-common": self._labels(self.S, "sha256:" + "c" * 64)},
            digests={("epirhandbook-common", "2.9"): self.D_NEW},
            diff_cache={self.S: []},
        )
        self.assertTrue(changed, msg=reason)
        self.assertIn("epirhandbook-common:2.9", reason)

    def test_missing_base_digest_label_is_changed(self):
        # Every image published before build_image.sh stamped the label.
        changed, reason = self._run(
            self.GROUP,
            labels={"epirhandbook-analysis": self._labels(self.S)},
            digests={("epirhandbook-common", "2.9"): self.D_NEW},
            diff_cache={self.S: []},
        )
        self.assertTrue(changed, msg=reason)
        self.assertIn(changed_images.BASE_DIGEST_LABEL, reason)
        self.assertIn("epirhandbook-common:2.9", reason)

    def test_unreadable_base_digest_is_changed(self):
        changed, reason = self._run(
            self.GROUP,
            labels={"epirhandbook-analysis": self._labels(self.S, self.D_OLD)},
            digests={},
            diff_cache={self.S: []},
        )
        self.assertTrue(changed, msg=reason)
        self.assertIn("epirhandbook-common:2.9", reason)
        self.assertIn("could not be read", reason)

    def test_label_equal_to_base_digest_and_no_own_change_is_unchanged(self):
        changed, reason = self._run(
            self.GROUP,
            labels={"epirhandbook-analysis": self._labels(self.S, self.D_NEW)},
            digests={("epirhandbook-common", "2.9"): self.D_NEW},
            diff_cache={self.S: []},
        )
        self.assertFalse(changed, msg=reason)
        # The base is read by its catalog name AND tag, from plan.parse_base.
        self.assertEqual(self.digest_reads, [("epirhandbook-common", "2.9")])

    def test_own_file_change_keeps_its_reason_when_the_base_matches(self):
        changed, reason = self._run(
            self.GROUP,
            labels={"epirhandbook-analysis": self._labels(self.S, self.D_NEW)},
            digests={("epirhandbook-common", "2.9"): self.D_NEW},
            diff_cache={self.S: ["epirhandbook/2.9/groups/analysis/packages_cran.txt"]},
        )
        self.assertTrue(changed)
        self.assertIn("own dir changed", reason)

    def test_image_without_a_base_is_unaffected(self):
        # rbase has base null: no base label, and no base digest is read.
        changed, reason = self._run(
            self.RBASE,
            labels={"rbase": self._labels(self.S)},
            digests={},
            diff_cache={self.S: []},
        )
        self.assertFalse(changed, msg=reason)
        self.assertEqual(reason, f"unchanged since published revision {self.S}")
        self.assertEqual(self.digest_reads, [])

    def test_image_not_live_ignores_its_base(self):
        # A moved base is the automatic rebuild that `live: false` opts out of.
        not_live = dict(self.GROUP, live=False)
        changed, reason = self._run(
            not_live,
            labels={"epirhandbook-analysis": self._labels(self.S)},
            digests={("epirhandbook-common", "2.9"): self.D_NEW},
            diff_cache={self.S: []},
        )
        self.assertFalse(changed, msg=reason)
        self.assertEqual(self.digest_reads, [])


if __name__ == "__main__":
    unittest.main()
