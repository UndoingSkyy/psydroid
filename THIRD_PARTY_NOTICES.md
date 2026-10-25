# Third-party notices

PsyDroid is distributed under the MIT license in LICENSE.

## Included components

- Qt for Python / PySide6 and Shiboken6: Qt Company and contributors;
  LGPLv3/GPLv3/commercial licensing, including Qt third-party notices.
  https://doc.qt.io/qtforpython-6/licenses.html
  Source: https://code.qt.io/cgit/pyside/pyside-setup.git/ and
  https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/
- Python: Python Software Foundation license. https://www.python.org/psf/license/
- gRPC: Apache-2.0. https://github.com/grpc/grpc
- Protocol Buffers: BSD-3-Clause. https://github.com/protocolbuffers/protobuf
- Generated emulator gRPC bindings: Apache-2.0; original headers retained in
  psydroid/proto. https://android.googlesource.com/platform/hardware/google/aemu/
- PyInstaller bootloader: GPL with distribution exception.
  https://pyinstaller.org/en/stable/license.html

The portable package includes license files extracted from installed dependency
distributions under `licenses/`, and the editable PsyDroid source in `source.zip`.
Qt DLLs remain separate in `_internal` and can be replaced with compatible
builds. You may modify and rebuild this application to use modified Qt libraries;
reverse engineering for debugging modifications to LGPL components is permitted.

## Separately downloaded components

The Android Emulator engine is based on open-source AOSP/QEMU. PsyDroid does
not modify or compile that engine. Official emulator binaries, adb and the Google
Play Android image are downloaded from Google's SDK repository at first setup.
They have separate licenses shown in the app, and are not included in this
repository or the portable ZIP. The Google Play image and services are not
MIT-licensed PsyDroid code.
https://developer.android.com/studio/terms
https://android.googlesource.com/platform/external/qemu/

Firefox, uBlock Origin and AdGuard DNS are optional integrations subject to
their providers' terms. PsyDroid is not affiliated with or endorsed by Google,
Qt or those providers.
