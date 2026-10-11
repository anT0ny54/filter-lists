"""publish.sh must survive a branch that moved while the build was running.

Each test uses a real bare remote plus two shallow clones: the "runner"
(which checked out early and then built) and a "racer" that pushes while the
runner is busy. That is exactly the failure from the update.yml run that
reported the branch as being at a different commit than expected.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish.sh"
GENERATED = ["filters.txt", "reports/history", "reports/source-outcomes.json"]
GUARDS = ["scripts/", "sources.yaml"]
ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test",
    "GIT_TERMINAL_PROMPT": "0",
}


def git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, env=ENV, text=True,
                          capture_output=True, check=check)


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "git and bash required")
class PublishRetryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.remote = self.tmp / "remote.git"
        seed = self.tmp / "seed"
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(self.remote))
        git(self.tmp, "init", "-q", "-b", "main", str(seed))
        write(seed, "README.md", "readme\n")
        write(seed, "sources.yaml", "sources: []\n")
        write(seed, "scripts/a.py", "pass\n")
        write(seed, "filters.txt", "old\n")
        write(seed, "reports/history/old-1.json", "{}\n")
        write(seed, "reports/history/old-2.json", "{}\n")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "seed")
        git(seed, "push", "-q", str(self.remote), "main")
        self.runner = self._clone("runner")
        self.racer = self._clone("racer")

    def _clone(self, name):
        dest = self.tmp / name
        git(self.tmp, "clone", "-q", "--depth", "1", "-b", "main", self.remote.as_uri(), str(dest))
        return dest

    def _race(self, rel, text):
        """Push a commit from the racer so the runner's push is non-fast-forward."""
        write(self.racer, rel, text)
        git(self.racer, "add", "-A")
        git(self.racer, "commit", "-q", "-m", f"racer: {rel}")
        git(self.racer, "push", "-q", "origin", "HEAD:main")

    def _build(self):
        """What the build step leaves behind in the runner's work tree."""
        write(self.runner, "filters.txt", "new\n")
        (self.runner / "reports/history/old-1.json").unlink()  # retention pruning
        write(self.runner, "reports/history/new-3.json", "{}\n")
        write(self.runner, "reports/source-outcomes.json", "{\"runs\": []}\n")

    def _publish(self, *, guards=True, extra_env=None, paths=None):
        cmd = ["bash", str(SCRIPT), "-m", "chore: publish"]
        if guards:
            for guard in GUARDS:
                cmd += ["--guard", guard]
        cmd += ["--", *(paths or GENERATED)]
        env = {**ENV, "PUBLISH_BRANCH": "main", "PUBLISH_RETRY_DELAY": "0", **(extra_env or {})}
        return subprocess.run(cmd, cwd=self.runner, env=env, text=True, capture_output=True)

    def _remote_show(self, rel):
        proc = git(self.tmp, "--git-dir", str(self.remote), "show", f"main:{rel}", check=False)
        return proc.stdout if proc.returncode == 0 else None

    def _remote_count(self):
        return int(git(self.tmp, "--git-dir", str(self.remote), "rev-list", "--count", "main").stdout)

    def test_plain_push_without_a_race(self):
        self._build()
        proc = self._publish()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._remote_show("filters.txt"), "new\n")

    def test_nothing_to_publish_is_a_noop(self):
        before = self._remote_count()
        proc = self._publish()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("No generated changes", proc.stdout)
        self.assertEqual(self._remote_count(), before)

    def test_branch_moved_by_unrelated_commit_is_retried(self):
        self._build()
        self._race("README.md", "edited elsewhere\n")
        proc = self._publish()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("moved during the build", proc.stderr)
        self.assertEqual(self._remote_show("README.md"), "edited elsewhere\n")  # racer kept
        self.assertEqual(self._remote_show("filters.txt"), "new\n")             # ours landed
        self.assertIsNone(self._remote_show("reports/history/old-1.json"))     # deletion propagated
        self.assertEqual(self._remote_show("reports/history/new-3.json"), "{}\n")
        self.assertEqual(self._remote_show("reports/history/old-2.json"), "{}\n")

    def test_generated_file_conflict_is_resolved_in_favour_of_new_build(self):
        # Another publisher rewrote filters.txt: a textual rebase would conflict.
        self._build()
        self._race("filters.txt", "someone else's build\n")
        proc = self._publish()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._remote_show("filters.txt"), "new\n")

    def test_changed_build_input_skips_publishing_stale_output(self):
        self._build()
        self._race("scripts/a.py", "print('new logic')\n")
        tip_before = self._remote_show("scripts/a.py")
        proc = self._publish()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("NOT published", proc.stderr)
        self.assertEqual(self._remote_show("filters.txt"), "old\n")
        self.assertEqual(self._remote_show("scripts/a.py"), tip_before)

    def test_without_guards_input_changes_do_not_block(self):
        self._build()
        self._race("scripts/a.py", "print('new logic')\n")
        proc = self._publish(guards=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._remote_show("filters.txt"), "new\n")

    def _race_on_every_push(self, times):
        """pre-push hook that makes the branch move again just before each of the first `times` pushes."""
        counter = self.tmp / "hook-count"
        counter.write_text("0")
        hook = self.runner / ".git" / "hooks" / "pre-push"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            f"n=$(cat {counter}); [ \"$n\" -lt {times} ] || exit 0\n"
            f"echo $((n+1)) > {counter}\n"
            f"cd {self.racer} || exit 1\n"
            f"git pull -q --rebase origin main >/dev/null 2>&1\n"
            f"echo \"race $n\" > race.txt && git add -A && git commit -q -m race && git push -q origin HEAD:main\n",
            encoding="utf-8")
        hook.chmod(0o755)

    def test_branch_that_moves_again_during_retry_is_retried_again(self):
        self._build()
        self._race_on_every_push(2)
        proc = self._publish()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("attempt 3)", proc.stdout)
        self.assertEqual(self._remote_show("filters.txt"), "new\n")
        self.assertEqual(self._remote_show("race.txt"), "race 1\n")

    def test_gives_up_after_max_attempts(self):
        self._build()
        self._race_on_every_push(99)
        proc = self._publish(extra_env={"PUBLISH_MAX_ATTEMPTS": "2"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("still rejected after 2 attempts", proc.stderr)
        self.assertEqual(self._remote_show("filters.txt"), "old\n")

    def test_non_retryable_push_failure_fails_fast(self):
        self._build()
        git(self.runner, "remote", "set-url", "origin", (self.tmp / "missing.git").as_uri())
        proc = self._publish()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not retrying", proc.stderr)

    def test_missing_optional_path_is_skipped(self):
        write(self.runner, "filters.txt", "new\n")
        proc = self._publish(paths=["filters.txt", "reports/does-not-exist.json"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._remote_show("filters.txt"), "new\n")

    def test_usage_errors(self):
        for args in ([], ["-m", "x"], ["-m", "x", "--", ], ["--bogus"]):
            with self.subTest(args=args):
                proc = subprocess.run(["bash", str(SCRIPT), *args], cwd=self.runner, env=ENV,
                                      text=True, capture_output=True)
                self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
