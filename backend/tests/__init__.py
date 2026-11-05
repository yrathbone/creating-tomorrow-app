"""Unit tests read uploads in-process for speed; tests/test_upload_security.py switches the isolated child process on for its own cases."""
import os

os.environ.setdefault("CT_ISOLATE_PARSING", "0")
