"""Turn off Electron fuses the packaged settings window never uses.

Fuses are build-time switches stored in the Electron executable after a fixed
sentinel: one version byte, one length byte, then one ASCII byte per fuse
("0" off, "1" on, "r" removed). The settings window is started by the app with
its own pipe and token, so it needs none of these ways for another program to
run code inside it:

- RunAsNode: ``ELECTRON_RUN_AS_NODE`` turns the executable into plain Node.
- EnableNodeOptionsEnvironmentVariable: ``NODE_OPTIONS`` such as ``--require``.
- EnableNodeCliInspectArguments: ``--inspect`` debugger arguments.

Only the bundled copy changes. Source runs and Playwright QA use
``settings-ui/node_modules/electron`` unchanged (QA needs ``--inspect``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

SENTINEL = b"dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX"
WIRE_VERSION = 1
# Indexes of @electron/fuses FuseV1Options.
RUN_AS_NODE = 0
NODE_OPTIONS = 2
NODE_CLI_INSPECT = 3
DISABLED = (RUN_AS_NODE, NODE_OPTIONS, NODE_CLI_INSPECT)


class FuseError(ValueError):
    pass


def read_fuses(data):
    """Return (offset of the first fuse byte, fuse bytes)."""
    index = data.find(SENTINEL)
    if index < 0 or data.find(SENTINEL, index + 1) >= 0:
        raise FuseError("expected exactly one fuse sentinel")
    start = index + len(SENTINEL)
    if data[start] != WIRE_VERSION:
        raise FuseError(f"unsupported fuse wire version {data[start]}")
    count = data[start + 1]
    return start + 2, bytes(data[start + 2 : start + 2 + count])


def disable_fuses(path):
    """Switch the ``DISABLED`` fuses off in place and return the new wire."""
    path = Path(path)
    data = bytearray(path.read_bytes())
    offset, fuses = read_fuses(data)
    for fuse in DISABLED:
        if fuse >= len(fuses) or fuses[fuse : fuse + 1] not in (b"0", b"1"):
            raise FuseError(f"fuse {fuse} is missing or removed")
        data[offset + fuse] = ord("0")
    path.write_bytes(data)
    return read_fuses(data)[1].decode("ascii")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args(argv)
    try:
        wire = disable_fuses(args.executable)
    except (OSError, FuseError) as error:
        print(f"electron fuses failed: {error}")
        return 1
    print(f"electron fuses: {wire}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
