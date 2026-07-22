import json
import os
import unittest
from unittest.mock import patch

from src import log_buffer


class LogBufferCoreTests(unittest.TestCase):
    def setUp(self):
        log_buffer.clear_logs()

    def test_append_and_snapshot(self):
        log_buffer.append_log("line 1")
        log_buffer.append_log("line 2")
        snap = log_buffer.snapshot_logs(lines=10)
        self.assertEqual(len(snap["logs"]), 2)
        self.assertEqual(snap["logs"][0]["text"], "line 1")
        self.assertEqual(snap["logs"][1]["text"], "line 2")
        self.assertFalse(snap["truncated"])
        self.assertEqual(snap["capacity"], log_buffer.LOG_CAPACITY)

    def test_monotonic_ids(self):
        log_buffer.append_log("a")
        id1 = log_buffer.snapshot_logs()["logs"][0]["id"]
        log_buffer.append_log("b")
        id2 = log_buffer.snapshot_logs()["logs"][-1]["id"]
        self.assertGreater(id2, id1)

    def test_cursor_returns_only_new_records(self):
        log_buffer.append_log("old")
        initial = log_buffer.snapshot_logs()
        cursor = initial["cursor"]
        log_buffer.append_log("new")
        incremental = log_buffer.snapshot_logs(after=cursor)
        self.assertEqual(len(incremental["logs"]), 1)
        self.assertEqual(incremental["logs"][0]["text"], "new")

    def test_stale_cursor_triggers_truncated(self):
        for i in range(log_buffer.LOG_CAPACITY + 1):
            log_buffer.append_log(f"line {i}")
        snap = log_buffer.snapshot_logs(after=0)
        self.assertTrue(snap["truncated"])

    def test_line_length_limit(self):
        long_line = "x" * (log_buffer.MAX_LOG_LINE_LENGTH + 100)
        log_buffer.append_log(long_line)
        snap = log_buffer.snapshot_logs()
        stored = snap["logs"][0]["text"]
        self.assertLessEqual(len(stored), log_buffer.MAX_LOG_LINE_LENGTH)

    def test_ring_eviction(self):
        for i in range(log_buffer.LOG_CAPACITY + 20):
            log_buffer.append_log(f"line {i}")
        snap = log_buffer.snapshot_logs(lines=log_buffer.LOG_CAPACITY)
        self.assertEqual(len(snap["logs"]), log_buffer.LOG_CAPACITY)

    def test_redact_vision_api_key(self):
        with patch.dict(os.environ, {"VISION_API_KEY": "sk-test-secret-key"}):
            log_buffer.append_log("my key is sk-test-secret-key")
        snap = log_buffer.snapshot_logs()
        self.assertNotIn("sk-test-secret-key", snap["logs"][0]["text"])
        self.assertIn("[REDACTED]", snap["logs"][0]["text"])

    def test_redact_bearer_token(self):
        log_buffer.append_log("Authorization: Bearer my-secret-token")
        snap = log_buffer.snapshot_logs()
        self.assertIn("[REDACTED]", snap["logs"][0]["text"])

    def test_redact_sk_pattern(self):
        log_buffer.append_log("token = sk-abc123def456ghijklmn")
        snap = log_buffer.snapshot_logs()
        self.assertIn("[REDACTED]", snap["logs"][0]["text"])

    def test_redact_empty_lines_skipped(self):
        log_buffer.append_log("")
        log_buffer.append_log("\n\n")
        self.assertEqual(log_buffer.snapshot_logs()["logs"], [])

    def test_get_recent_logs_compat(self):
        for i in range(10):
            log_buffer.append_log(f"line {i}")
        recent = log_buffer.get_recent_logs(lines=3)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[-1], "line 9")
        self.assertIsInstance(recent, list)
        self.assertIsInstance(recent[0], str)

    def test_get_recent_logs_default(self):
        log_buffer.append_log("test")
        recent = log_buffer.get_recent_logs()
        self.assertEqual(recent, ["test"])
        self.assertIsInstance(recent, list)
        self.assertIsInstance(recent[0], str)

    def test_get_recent_logs_zero_lines(self):
        log_buffer.append_log("test")
        self.assertEqual(log_buffer.get_recent_logs(lines=0), [])

    def test_get_recent_logs_invalid_lines(self):
        log_buffer.append_log("test")
        self.assertEqual(log_buffer.get_recent_logs(lines="invalid"), ["test"])

    def test_snapshot_invalid_lines(self):
        log_buffer.append_log("test")
        snap = log_buffer.snapshot_logs(lines="invalid")
        self.assertEqual(len(snap["logs"]), 1)
        snap = log_buffer.snapshot_logs(lines=-1)
        self.assertEqual(len(snap["logs"]), 1)
        snap = log_buffer.snapshot_logs(lines=9999999999)
        self.assertEqual(len(snap["logs"]), 1)

    def test_snapshot_invalid_after(self):
        log_buffer.append_log("test")
        snap = log_buffer.snapshot_logs(after="invalid")
        self.assertEqual(len(snap["logs"]), 1)

    def test_concurrent_append_and_snap(self):
        def writer():
            for i in range(50):
                log_buffer.append_log(f"w{i}")

        threads = []
        for _ in range(5):
            t = __import__("threading").Thread(target=writer)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        snap = log_buffer.snapshot_logs()
        self.assertGreater(len(snap["logs"]), 0)
        self.assertLessEqual(len(snap["logs"]), log_buffer.LOG_CAPACITY)

    def test_tee_install_restore(self):
        import sys
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        try:
            log_buffer.install_capture()
            self.assertIsNot(sys.stdout, original_stdout)
            self.assertIsInstance(sys.stdout, log_buffer.TeeOutput)
            sys.stdout.write("tee test\n")
            snap = log_buffer.snapshot_logs()
            self.assertTrue(any("tee test" in entry["text"] for entry in snap["logs"]))
        finally:
            log_buffer.restore_capture()
            log_buffer.restore_capture()
            self.assertIs(sys.stdout, original_stdout)
            self.assertIs(sys.stderr, original_stderr)


if __name__ == "__main__":
    unittest.main()