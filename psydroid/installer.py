import hashlib
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import paths

REPOSITORY = "https://dl.google.com/android/repository/"
STABLE = "channel-0"

IMAGE_TAG = "google_apis_playstore"
IMAGE_ABI = "x86_64"
IMAGE_REPOSITORY = f"{REPOSITORY}sys-img/{IMAGE_TAG}/"
# Android 15 stays known so existing instances keep running, but new instances get 16 or 11
ANDROID_VERSIONS = {"36": "Android 16", "35": "Android 15", "30": "Android 11"}
DEFAULT_API = "36"
IMAGE_NAME = ANDROID_VERSIONS[DEFAULT_API]


def image_dir(api):
    return Path("system-images", f"android-{api}", IMAGE_TAG, IMAGE_ABI)


def image_installed(api):
    return package_installed(image_dir(api))


def package_installed(folder):
    """An interrupted extraction must not look like an installed package."""
    folder = Path(folder)
    required = {
        "platform-tools": ("adb.exe",),
        "emulator": ("emulator.exe",),
        # Not userdata.img: Android 16 images ship a data folder instead, and requiring it re-downloaded them
        IMAGE_ABI: ("system.img", "source.properties"),
    }.get(folder.name)
    root = paths.SDK / folder
    return bool(required) and all((root / name).is_file() and (root / name).stat().st_size > 0
                                  for name in required)


REQUIRED = [Path("platform-tools"), Path("emulator"), image_dir(DEFAULT_API)]


@dataclass
class Package:
    label: str
    url: str
    size: int
    sha1: str
    license: str
    folder: Path

    @property
    def installed(self):
        return package_installed(self.folder)


def is_installed():
    # Any Android image will do: an instance whose image is missing downloads it when it starts,
    # so updating PsyDroid never blocks existing instances behind a new default image
    return all(package_installed(folder) for folder in REQUIRED[:2]) and any(map(image_installed, ANDROID_VERSIONS))


def resolve(api=DEFAULT_API, tools=True):
    repository = fetch_xml(REPOSITORY + "repository2-3.xml")
    images = fetch_xml(IMAGE_REPOSITORY + "sys-img2-3.xml")
    packages = []
    if tools:
        packages += [newest(repository, "platform-tools", REPOSITORY, "adb", REQUIRED[0]),
                     newest(repository, "emulator", REPOSITORY, "the emulator", REQUIRED[1])]
    packages.append(newest(images, f"system-images;android-{api};{IMAGE_TAG};{IMAGE_ABI}",
                           IMAGE_REPOSITORY, ANDROID_VERSIONS[api], image_dir(api)))
    texts = {**licenses(images), **licenses(repository)}
    return packages, {p.license: texts.get(p.license, "") for p in packages}


def install(packages, progress):
    paths.DOWNLOADS.mkdir(parents=True, exist_ok=True)
    for package in packages:
        if package.installed:
            continue
        archive = download(package, progress)
        extract(archive, paths.SDK / package.folder,
                lambda done, total: progress(package, done, total, "unpack"))
        archive.unlink()
    shutil.rmtree(paths.DOWNLOADS, ignore_errors=True)


def fetch_xml(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return ET.fromstring(response.read())


def local(element):
    return element.tag.rsplit("}", 1)[-1]


def first(element, name):
    return next((child for child in element.iter() if local(child) == name), None)


def licenses(root):
    return {element.get("id"): element.text.strip() for element in root if local(element) == "license"}


def newest(root, sdk_path, base_url, label, folder):
    best = None
    for package in root:
        if local(package) != "remotePackage" or package.get("path") != sdk_path:
            continue
        channel = first(package, "channelRef")
        if channel is None or channel.get("ref") != STABLE:
            continue
        revision = tuple(int(part.text) for part in first(package, "revision") if part.text.isdigit())
        for archive in package.iter():
            if local(archive) != "archive" or not runs_on_windows(archive):
                continue
            if best is None or revision > best[0]:
                complete = first(archive, "complete")
                best = revision, Package(
                    label=label,
                    url=base_url + first(complete, "url").text,
                    size=int(first(complete, "size").text),
                    sha1=first(complete, "checksum").text,
                    license=first(package, "uses-license").get("ref"),
                    folder=folder,
                )
    if best is None:
        raise RuntimeError(f"Google's repository has no Windows build of {sdk_path}")
    return best[1]


def runs_on_windows(archive):
    host = first(archive, "host-os")
    arch = first(archive, "host-arch")
    return (host is None or host.text == "windows") and (arch is None or arch.text == "x64")


def download(package, progress):
    paths.DOWNLOADS.mkdir(parents=True, exist_ok=True)
    final = paths.DOWNLOADS / Path(package.url).name
    if final.exists():
        progress(package, package.size, package.size, "verify")
        if verified(final, package):
            return final
        final.unlink()
    partial = final.with_suffix(".part")
    have = partial.stat().st_size if partial.exists() else 0
    if have > package.size:
        partial.unlink()
        have = 0

    # Retry once without a Range header when a server rejects or misinterprets
    # a resume request. Keep interrupted, valid partial transfers for next time.
    for attempt in range(2):
        if have == package.size:
            break
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            response = urllib.request.urlopen(urllib.request.Request(package.url, headers=headers), timeout=60)
        except urllib.error.HTTPError as error:
            error.close()
            if error.code == 416 and have and attempt == 0:
                partial.unlink(missing_ok=True)
                have = 0
                continue
            raise
        with response:
            if response.status == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                valid = match and int(match[1]) == have and int(match[3]) == package.size \
                    and have <= int(match[2]) < package.size
                if not valid:
                    partial.unlink(missing_ok=True)
                    have = 0
                    if attempt == 0:
                        continue
                    raise RuntimeError(f"The server returned an invalid download range for {package.label}. Try again.")
            elif response.status == 200:
                have = 0
            else:
                raise RuntimeError(f"The server could not download {package.label} (HTTP {response.status}).")
            with open(partial, "ab" if have else "wb") as file:
                while chunk := response.read(1 << 20):
                    file.write(chunk)
                    have += len(chunk)
                    progress(package, have, package.size, "download")
                    if have > package.size:
                        break
        break

    if have < package.size:
        raise RuntimeError(f"The download of {package.label} was interrupted. Try again to resume it.")
    progress(package, package.size, package.size, "verify")
    if not verified(partial, package):
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"The download of {package.label} was damaged. Try again.")
    partial.replace(final)
    return final


def verified(file, package):
    if not file.is_file() or file.stat().st_size != package.size:
        return False
    digest = hashlib.sha1()
    with open(file, "rb") as source:
        while chunk := source.read(1 << 22):
            digest.update(chunk)
    return digest.hexdigest() == package.sha1.lower()


def extract(archive, destination, progress):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-unpacking-", dir=destination.parent))
    previous = destination.with_name(f".{destination.name}-previous-{uuid.uuid4().hex}")
    try:
        with zipfile.ZipFile(archive) as zipped:
            members = zipped.infolist()
            # Validate the entire archive before writing anything. Windows drive
            # names, backslashes, alternate streams and symlinks need explicit
            # checks even when the archive is inspected on another platform.
            targets = []
            for member in members:
                name = member.filename.replace("\\", "/")
                path = PurePosixPath(name)
                mode = stat.S_IFMT(member.external_attr >> 16)
                target = staging.joinpath(*path.parts).resolve()
                invalid_windows_name = any(part.endswith((".", " ")) or re.fullmatch(
                    r"(?i)(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])", part.split(".")[0])
                    for part in path.parts)
                if path.is_absolute() or PureWindowsPath(name).drive or ".." in path.parts \
                        or ":" in name or "\x00" in name or not target.is_relative_to(staging.resolve()) \
                        or invalid_windows_name or mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise RuntimeError("The downloaded archive contains an unsafe file path.")
                targets.append(target)
            total = sum(member.file_size for member in members) or 1
            done = 0
            for member, target in zip(members, targets):
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zipped.open(member) as source, open(target, "wb") as output:
                        shutil.copyfileobj(source, output, 1 << 20)
                done += member.file_size
                progress(done, total)
        contents = list(staging.iterdir())
        if not contents:
            raise RuntimeError("The downloaded archive is empty. Try again.")
        source = contents[0] if len(contents) == 1 and contents[0].is_dir() else staging
        # Both renames stay on the destination volume. The old runtime remains
        # intact through extraction and is restored if promotion fails.
        if destination.exists():
            destination.rename(previous)
        try:
            source.rename(destination)
        except BaseException:
            if previous.exists() and not destination.exists():
                previous.rename(destination)
            raise
        shutil.rmtree(previous, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
