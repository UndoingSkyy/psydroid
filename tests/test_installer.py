"""Installer integrity and recovery tests; no SDK downloads or licenses needed."""
import hashlib
import io
import stat
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from psydroid import installer


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {}


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.downloads = self.root / "downloads"
        self.downloads.mkdir()
        self.addCleanup(patch.stopall)
        patch.object(installer.paths, "DOWNLOADS", self.downloads).start()
        patch.object(installer.paths, "SDK", self.root / "sdk").start()
        self.payload = b"trusted-runtime-content"
        self.package = installer.Package("test runtime", "https://example.invalid/runtime.zip",
                                         len(self.payload), hashlib.sha1(self.payload).hexdigest(),
                                         "test-license", Path("emulator"))
        self.final = self.downloads / "runtime.zip"
        self.partial = self.downloads / "runtime.part"
        self.progress = lambda *args: None

    def download(self, responses):
        with patch.object(installer.urllib.request, "urlopen", side_effect=responses) as request:
            result = installer.download(self.package, self.progress)
        self.assertEqual(result.read_bytes(), self.payload)
        self.assertFalse(self.partial.exists())
        return request

    def test_verified_cached_download_does_not_request_network(self):
        self.final.write_bytes(self.payload)
        self.assertEqual(self.download([]).call_count, 0)

    def test_corrupt_cached_download_is_replaced(self):
        self.final.write_bytes(b"X" * len(self.payload))
        self.download([Response(self.payload)])

    def test_wrong_size_cached_download_is_replaced(self):
        self.final.write_bytes(b"bad")
        self.download([Response(self.payload)])

    def test_valid_complete_partial_is_promoted(self):
        self.partial.write_bytes(self.payload)
        self.assertEqual(self.download([]).call_count, 0)

    def test_valid_range_resumes_partial(self):
        self.partial.write_bytes(self.payload[:5])
        response = Response(self.payload[5:], 206,
                            {"Content-Range": f"bytes 5-{len(self.payload) - 1}/{len(self.payload)}"})
        request = self.download([response])
        self.assertEqual(request.call_args.args[0].get_header("Range"), "bytes=5-")

    def test_full_response_to_range_replaces_partial(self):
        self.partial.write_bytes(self.payload[:5])
        self.download([Response(self.payload)])

    def test_invalid_range_retries_from_zero(self):
        self.partial.write_bytes(self.payload[:5])
        request = self.download([Response(b"bad", 206, {"Content-Range": "bytes 0-2/3"}),
                                 Response(self.payload)])
        self.assertEqual(request.call_count, 2)
        self.assertIsNone(request.call_args.args[0].get_header("Range"))

    def test_repeated_invalid_range_fails_without_infinite_retry(self):
        self.partial.write_bytes(self.payload[:5])
        with patch.object(installer.urllib.request, "urlopen",
                          side_effect=[Response(b"bad", 206), Response(b"bad", 206)]) as request:
            with self.assertRaisesRegex(RuntimeError, "invalid download range"):
                installer.download(self.package, self.progress)
        self.assertEqual(request.call_count, 2)
        self.assertFalse(self.final.exists())
        self.assertFalse(self.partial.exists())

    def test_range_not_satisfiable_retries_from_zero(self):
        self.partial.write_bytes(self.payload[:5])
        error = urllib.error.HTTPError(self.package.url, 416, "Range not satisfiable", {}, None)
        request = self.download([error, Response(self.payload)])
        self.assertEqual(request.call_count, 2)
        self.assertIsNone(request.call_args.args[0].get_header("Range"))

    def test_truncated_response_preserved_for_later_resume(self):
        with patch.object(installer.urllib.request, "urlopen", return_value=Response(self.payload[:5])):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                installer.download(self.package, self.progress)
        self.assertEqual(self.partial.read_bytes(), self.payload[:5])
        self.assertFalse(self.final.exists())

    def test_checksum_failure_removes_partial(self):
        with patch.object(installer.urllib.request, "urlopen", return_value=Response(b"X" * len(self.payload))):
            with self.assertRaisesRegex(RuntimeError, "damaged"):
                installer.download(self.package, self.progress)
        self.assertFalse(self.partial.exists())
        self.assertFalse(self.final.exists())

    def test_oversized_partial_is_restarted(self):
        self.partial.write_bytes(self.payload + b"extra")
        request = self.download([Response(self.payload)])
        self.assertIsNone(request.call_args.args[0].get_header("Range"))

    def test_oversized_response_is_rejected(self):
        with patch.object(installer.urllib.request, "urlopen", return_value=Response(self.payload + b"extra")):
            with self.assertRaisesRegex(RuntimeError, "damaged"):
                installer.download(self.package, self.progress)
        self.assertFalse(self.partial.exists())

    def archive(self, entries):
        file = self.root / "package.zip"
        with zipfile.ZipFile(file, "w") as zipped:
            for name, content in entries:
                zipped.writestr(name, content)
        return file

    def existing_runtime(self):
        destination = self.root / "sdk" / "emulator"
        destination.mkdir(parents=True)
        (destination / "emulator.exe").write_bytes(b"working-runtime")
        return destination

    def assert_runtime_preserved(self, destination):
        self.assertEqual((destination / "emulator.exe").read_bytes(), b"working-runtime")
        self.assertEqual(sorted(path.name for path in destination.parent.iterdir()), ["emulator"])

    def test_unsafe_archive_keeps_old_runtime_and_writes_nothing_outside(self):
        destination = self.existing_runtime()
        for unsafe in ("../outside", "/outside", "C:/outside", "dir/../../outside",
                       "..\\outside", "file:stream", "\\\\server\\share\\outside", "NUL",
                       "dir/COM1.txt", "dir. /outside", ".. /outside"):
            with self.subTest(path=unsafe):
                archive = self.archive([("emulator/emulator.exe", b"new"), (unsafe, b"bad")])
                with self.assertRaisesRegex(RuntimeError, "unsafe"):
                    installer.extract(archive, destination, self.progress)
                self.assert_runtime_preserved(destination)
                self.assertFalse((self.root / "outside").exists())

    def test_symlink_archive_rejected(self):
        destination = self.existing_runtime()
        member = zipfile.ZipInfo("emulator/link")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = self.archive([(member, "../../outside")])
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            installer.extract(archive, destination, self.progress)
        self.assert_runtime_preserved(destination)

    def test_failed_extraction_keeps_old_runtime(self):
        destination = self.existing_runtime()
        archive = self.archive([("emulator/emulator.exe", b"replacement")])
        def interrupted(*args):
            raise OSError("disk full")
        with self.assertRaisesRegex(OSError, "disk full"):
            installer.extract(archive, destination, interrupted)
        self.assert_runtime_preserved(destination)

    def test_empty_archive_keeps_old_runtime(self):
        destination = self.existing_runtime()
        with self.assertRaisesRegex(RuntimeError, "empty"):
            installer.extract(self.archive([]), destination, self.progress)
        self.assert_runtime_preserved(destination)

    def test_promotion_failure_rolls_back_old_runtime(self):
        destination = self.existing_runtime()
        archive = self.archive([("emulator/emulator.exe", b"replacement")])
        original_rename = Path.rename
        def failing_rename(source, target):
            if "-unpacking-" in str(source) and Path(target) == destination:
                raise OSError("promotion failed")
            return original_rename(source, target)
        with patch.object(Path, "rename", failing_rename):
            with self.assertRaisesRegex(OSError, "promotion failed"):
                installer.extract(archive, destination, self.progress)
        self.assert_runtime_preserved(destination)

    def test_successful_extraction_replaces_old_runtime(self):
        destination = self.existing_runtime()
        archive = self.archive([("emulator/emulator.exe", b"replacement"),
                                ("emulator/lib/runtime.dll", b"library")])
        installer.extract(archive, destination, self.progress)
        self.assertEqual((destination / "emulator.exe").read_bytes(), b"replacement")
        self.assertEqual((destination / "lib/runtime.dll").read_bytes(), b"library")
        self.assertEqual(sorted(path.name for path in destination.parent.iterdir()), ["emulator"])

    def test_empty_package_directory_not_installed(self):
        destination = installer.paths.SDK / "emulator"
        destination.mkdir(parents=True)
        self.assertFalse(self.package.installed)
        (destination / "emulator.exe").touch()
        self.assertFalse(self.package.installed)
        (destination / "emulator.exe").write_bytes(b"runtime")
        self.assertTrue(self.package.installed)

    def test_android_16_image_without_userdata_is_installed(self):
        # Google's Android 16 image ships a data folder instead of userdata.img. Requiring that file
        # made a finished 1.9 GB install look missing, so every start downloaded it again
        folder = installer.paths.SDK / installer.image_dir("36")
        (folder / "data").mkdir(parents=True)
        self.assertFalse(installer.image_installed("36"))
        for name in ("system.img", "source.properties", "ramdisk.img", "vendor.img"):
            (folder / name).write_bytes(b"image")
        self.assertTrue(installer.image_installed("36"))
        (folder / "system.img").write_bytes(b"")
        self.assertFalse(installer.image_installed("36"))


if __name__ == "__main__":
    unittest.main()
