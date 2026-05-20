"""Service-test conftest.

Forces all Raven-related paths into a temp scratch dir so the module-level
``raven_package_service`` singleton does not try to mkdir absolute paths
like ``/app/data/raven`` that come from the production .env.
"""

from __future__ import annotations

import os
import tempfile


_scratch = tempfile.mkdtemp(prefix="raven-svc-test-")
os.environ.setdefault("RAVEN_DATA_DIR", os.path.join(_scratch, "raven"))
os.environ.setdefault("RAVEN_METADATA_FILE", os.path.join(_scratch, "raven", "package-metadata.json"))
os.environ.setdefault("UPLOAD_DIR", os.path.join(_scratch, "raven", "uploads"))
# Override any production .env hand-set values too.
os.environ["RAVEN_DATA_DIR"] = os.path.join(_scratch, "raven")
os.environ["RAVEN_METADATA_FILE"] = os.path.join(_scratch, "raven", "package-metadata.json")
os.environ["UPLOAD_DIR"] = os.path.join(_scratch, "raven", "uploads")
