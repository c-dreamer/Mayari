"""Check release CLI forwarding with isolated fixtures; no real builds or uploads."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


RELEASE_SCRIPT = Path(__file__).resolve().parents[1] / "release-ios.sh"


class ReleaseIosTests(unittest.TestCase):
    def setUp(self):
        # Keep every fixture inside the repository; never touch its real build tree.
        self.temp = tempfile.TemporaryDirectory(prefix=".release-ios-test-", dir=RELEASE_SCRIPT.parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        scripts = self.root / "scripts"
        scripts.mkdir()
        shutil.copy2(RELEASE_SCRIPT, scripts / "release-ios.sh")
        (scripts / "check-ios-dist.sh").write_text(
            'printf "%s\\n" "$@" > "$RELEASE_TEST_ROOT/preflight-args"\n'
            'exit "${RELEASE_TEST_PREFLIGHT_EXIT:-0}"\n'
        )
        (self.root / "ios").mkdir()
        (self.root / "ios/ExportOptions.plist").touch()
        (self.root / "pubspec.yaml").write_text("version: 1.2.3+45\n")
        binaries = self.root / "bin"
        binaries.mkdir()
        flutter = binaries / "flutter"
        flutter.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "root = pathlib.Path(os.environ['RELEASE_TEST_ROOT'])\n"
            "with (root / 'flutter-args').open('a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if sys.argv[1:] == ['pub', 'get']:\n"
            "    sys.exit(0)\n"
            "if sys.argv[1:3] != ['build', 'ipa']:\n"
            "    sys.exit('unexpected Flutter invocation')\n"
            "if '--no-codesign' in sys.argv:\n"
            "    (root / 'build/ios/archive/Runner.xcarchive').mkdir(parents=True)\n"
            "else:\n"
            "    ipa = root / 'build/ios/ipa/Runner.ipa'\n"
            "    ipa.parent.mkdir(parents=True)\n"
            "    ipa.touch()\n"
        )
        flutter.chmod(0o755)
        asc = binaries / "asc"
        asc.write_text('#!/bin/bash\necho "Unexpected upload" >&2\nexit 99\n')
        asc.chmod(0o755)
        self.env = {
            "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
            "RELEASE_TEST_ROOT": str(self.root),
        }

    def run_release(self, *args):
        return subprocess.run(
            ["bash", str(self.root / "scripts/release-ios.sh"), *args],
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def flutter_calls(self):
        return [json.loads(line) for line in (self.root / "flutter-args").read_text().splitlines()]

    def assert_no_work(self):
        self.assertFalse((self.root / "preflight-args").exists())
        self.assertFalse((self.root / "flutter-args").exists())

    def test_default_build_keeps_runner_without_flavor(self):
        result = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "preflight-args").read_text().splitlines(), ["--scheme", "Runner"])
        calls = self.flutter_calls()
        self.assertEqual(calls[0], ["pub", "get"])
        self.assertEqual(calls[1], [
            "build", "ipa", "--release", "--build-name=1.2.3", "--build-number=45",
            f"--export-options-plist={self.root / 'ios/ExportOptions.plist'}",
        ])
        self.assertIn("IPA ready:", result.stdout)

    def test_custom_scheme_reaches_preflight_and_flutter(self):
        export_options = self.root / "ios/Custom Export.plist"
        export_options.touch()
        result = self.run_release("--scheme", "staging", "--export-options", str(export_options), "--no-codesign")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "preflight-args").read_text().splitlines(), ["--scheme", "staging"])
        build = self.flutter_calls()[1]
        self.assertIn("--flavor=staging", build)
        self.assertIn(f"--export-options-plist={export_options}", build)
        self.assertIn("--no-codesign", build)
        self.assertIn("Unsigned archive ready:", result.stdout)

    def test_explicit_runner_is_not_a_flavor(self):
        result = self.run_release("--scheme", "Runner", "--no-codesign")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(arg.startswith("--flavor") for arg in self.flutter_calls()[1]))

    def test_workspace_override_is_rejected_before_any_work(self):
        result = self.run_release("--workspace", "ios/Custom Workspace.xcworkspace")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--workspace is not supported", result.stderr)
        self.assert_no_work()

    def test_missing_or_empty_option_values_are_rejected(self):
        for option in ("--scheme", "--export-options", "--dist"):
            for suffix in ((), ("",), ("--no-codesign",)):
                with self.subTest(option=option, suffix=suffix):
                    result = self.run_release(option, *suffix)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(f"{option} requires a value", result.stderr)
                    self.assert_no_work()

    def test_invalid_distribution_and_unsigned_upload_are_rejected(self):
        for args, error in (
            (("--dist", "invalid"), "--dist must be one of"),
            (("--upload", "--no-codesign"), "--upload cannot be combined"),
        ):
            with self.subTest(args=args):
                result = self.run_release(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn(error, result.stderr)
                self.assert_no_work()

    def test_preflight_failure_stops_flutter(self):
        self.env["RELEASE_TEST_PREFLIGHT_EXIT"] = "17"
        result = self.run_release("--scheme", "staging", "--no-codesign")
        self.assertEqual(result.returncode, 17)
        self.assertFalse((self.root / "flutter-args").exists())

    def test_help_explains_supported_options_without_work(self):
        result = self.run_release("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Flutter --flavor", result.stdout)
        self.assertIn("custom workspaces are not supported", result.stdout)
        self.assert_no_work()


if __name__ == "__main__":
    unittest.main()
