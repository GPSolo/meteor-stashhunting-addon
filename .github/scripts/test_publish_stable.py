"""Exercise stable publishing without network access or real release changes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("publish-stable.sh")


class StablePublishingTests(unittest.TestCase):
    def publish(self, mode="existing", version="0.16.8-26.3", branch="26.3"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir()
            (root / "build/libs").mkdir(parents=True)
            (root / "gradle.properties").write_text(
                f"mod_version={version}\narchives_base_name=jefff-mod\n")
            (root / f"build/libs/jefff-mod-{version}.jar").write_bytes(b"test jar")
            gh = root / "bin/gh"
            gh.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys
args = sys.argv[1:]
with open('calls.jsonl', 'a') as calls:
    calls.write(json.dumps(args) + '\\n')
mode = os.environ['TEST_MODE']
if args[:2] == ['release', 'view']:
    count = pathlib.Path('views')
    seen = int(count.read_text()) if count.exists() else 0
    count.write_text(str(seen + 1))
    sys.exit(0 if mode in ('existing', 'upload-failure') or (mode == 'race' and seen > 0) else 1)
if args[:2] == ['release', 'create']:
    sys.exit(1 if mode in ('race', 'create-failure') else 0)
if args[:2] == ['release', 'upload']:
    sys.exit(1 if mode == 'upload-failure' else 0)
sys.exit(0)
''')
            gh.chmod(0o755)
            git = root / "bin/git"
            git.write_text("#!/bin/sh\necho 0123456789abcdef\n")
            git.chmod(0o755)
            env = dict(os.environ, PATH=str(root / "bin") + os.pathsep + os.environ["PATH"],
                       TEST_MODE=mode, RELEASE_BRANCH=branch, GITHUB_REPOSITORY="test/repo")
            result = subprocess.run(["bash", str(SCRIPT)], cwd=root, env=env,
                                    capture_output=True, text=True)
            log = root / "calls.jsonl"
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_existing_release_gets_only_own_asset(self):
        result, calls = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        upload = next(c for c in calls if c[1] == "upload")
        self.assertEqual(upload[2:4], ["0.16.8", "build/libs/jefff-mod-0.16.8-26.3.jar"])
        self.assertIn("--clobber", upload)
        self.assertFalse(any(c[1] in ("create", "delete", "delete-asset") for c in calls))
        edit = next(c for c in calls if c[1] == "edit")
        self.assertNotIn("--notes", edit)
        self.assertNotIn("--title", edit)

    def test_new_release_uses_shared_tag_and_title(self):
        result, calls = self.publish(mode="new")
        self.assertEqual(result.returncode, 0, result.stderr)
        create = next(c for c in calls if c[1] == "create")
        self.assertEqual(create[2], "0.16.8")
        self.assertEqual(create[create.index("--title") + 1], "0.16.8")

    def test_concurrent_creation_still_uploads(self):
        result, calls = self.publish(mode="race")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(c[1] == "upload" for c in calls))

    def test_publication_failures_are_not_swallowed(self):
        for mode in ("upload-failure", "create-failure"):
            with self.subTest(mode=mode):
                result, calls = self.publish(mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[1] == "edit" for c in calls))

    def test_wrong_branch_is_rejected(self):
        result, calls = self.publish(version="0.16.8-26.2")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [])

    def test_legacy_snapshot_jar_uses_shared_stable_name(self):
        result, calls = self.publish(version="0.16.8-SNAPSHOT-1.21.1", branch="1.21.1")
        self.assertEqual(result.returncode, 0, result.stderr)
        upload = next(c for c in calls if c[1] == "upload")
        self.assertEqual(upload[2:4], ["0.16.8", "build/libs/jefff-mod-0.16.8-1.21.1.jar"])


if __name__ == "__main__":
    unittest.main()
