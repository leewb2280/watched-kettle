"""Project regression tests."""

import atexit
import os
import shutil
import tempfile


# Tests must never read or write the developer's real settings, records or hook
# runtime under %LOCALAPPDATA%\WatchedKettle. Objects built without explicit
# settings fall back to that folder, and the hook spool path is resolved when
# its module is imported, so this runs before any test module is loaded. The
# runners use ``discover -s tests -t .`` so this package is always imported.
ISOLATED_LOCAL_APP_DATA = tempfile.mkdtemp(prefix="watched-kettle-tests-")
os.environ["LOCALAPPDATA"] = ISOLATED_LOCAL_APP_DATA
# Claude Code transcripts, settings and account file live here instead of the
# developer's ~/.claude (stage 13 reads transcripts for task history).
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(ISOLATED_LOCAL_APP_DATA, "claude")
atexit.register(shutil.rmtree, ISOLATED_LOCAL_APP_DATA, ignore_errors=True)
