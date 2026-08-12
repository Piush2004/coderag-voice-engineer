"""Point storage at an isolated temp dir before any app module is imported, so tests
never touch the real ./data used by the running dev server."""
import os
import tempfile

os.environ["CODERAG_DATA_DIR"] = tempfile.mkdtemp(prefix="coderag_test_")
