# Third-Party Notices

## Electron settings interface

The Windows distribution includes Electron 44.4.5 (MIT), its Chromium/Node.js
components, React and React DOM 19.3.0 (MIT), and Lucide React 0.468.0 (ISC).
The pinned dependency inventory is `settings-ui/pnpm-lock.yaml` in the source.
The package includes Electron's `settings-ui/LICENSE` and
`settings-ui/LICENSES.chromium.html`, plus the complete React, React DOM, and
Lucide notices under `settings-ui/licenses`. Build-only tooling and Playwright
are not included in the installed app. The UI uses the bundled Pretendard font
(see below).

## Python runtime and libraries

The Windows bundle is built with PyInstaller and includes the following
unmodified components. Their complete license texts are copied into the
`licenses` folder beside the executable at build time, and
`licenses/DEPENDENCIES.json` records the exact versions of each build.

- Python 3.14 runtime — Python Software Foundation License
  (`licenses/PYTHON_LICENSE.txt`)
- PySide6, Shiboken6 6.11 and the Qt 6 libraries they load — GNU Lesser General
  Public License v3 (`licenses/PySide6*`, `licenses/shiboken6`). Qt is used
  through the unmodified, dynamically loaded libraries under the bundle's
  `_internal/PySide6` folder, which a user may replace with compatible builds.
  Qt and Qt for Python source code is available from https://code.qt.io.
- Pillow 13 — MIT-CMU (HPND) License, including the notices of the image
  libraries Pillow bundles (`licenses/Pillow`)
- Babel 2.17 — BSD-3-Clause License and Unicode CLDR data notices
  (`licenses/Babel`)
- PyInstaller 6 bootloader — GNU General Public License v2 or later with the
  PyInstaller bootloader exception, which permits distributing the bundled
  application under its own terms (`licenses/PyInstaller`)

## Desktop Pet Agent

Parts of `watched_kettle/state/events.py` and
`watched_kettle/state/session_manager.py` are Python
adaptations of the event normalization and session aggregation designs from:

- Project: `yangbuyiya/desktop-pet`
- Source: https://github.com/yangbuyiya/desktop-pet
- Referenced commit: `6684953cc63d599003600d2ded66230277e75afc`
- Referenced files: `src/agent-events.js`, `src/session-manager.js`
- License: MIT

MIT License

Copyright (c) 2026 Yang Buyi <yangbuyiya@duck.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Pretendard

The application bundles the unmodified Regular, Medium, SemiBold, and Bold faces of
Pretendard 1.3.9 for its user interface.

- Project: `orioncactus/pretendard`
- Source: https://github.com/orioncactus/pretendard
- Version: 1.3.9
- License: SIL Open Font License 1.1

Copyright (c) 2021, Kil Hyung-jin (https://github.com/orioncactus/pretendard),
with Reserved Font Name "Pretendard".

Copyright 2014-2021 Adobe (http://www.adobe.com/),
with Reserved Font Name "Source".

Copyright (c) 2016 The Inter Project Authors (https://github.com/rsms/inter),
with Reserved Font Name "Inter".

Copyright 2021 The M+ FONTS Project Authors (https://github.com/coz-m/MPLUS_FONTS),
with Reserved Font Name "M PLUS 1".

The complete license text is stored at `assets/fonts/Pretendard/OFL.txt` in
the source tree and distributed as `PRETENDARD_OFL.txt` beside the executable.
