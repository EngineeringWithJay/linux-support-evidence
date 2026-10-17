"""Negative controls for evidence normalization, CPU oracle and TCP identity."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

from compare import normalize

TOOLS = Path(__file__).parent


class EvidenceTests(unittest.TestCase):
    def test_variable_pid_and_cpu_measurement(self):
        a = 'started_pid=12\n{"pid": 12, "cpu_percent_one_core": 98.5}\n/proc/12/stat\n'
        b = 'started_pid=29\n{"pid": 29, "cpu_percent_one_core": 91.0}\n/proc/29/stat\n'
        self.assertEqual(normalize(a), normalize(b))

    def test_fault_and_service_identity_are_not_normalized_away(self):
        for before, after in (
            ("errno=98 EADDRINUSE", "errno=13 EACCES"),
            ("service=app status=ok", "service=incumbent status=ok"),
            ("PORT=8080", "PORT=8081"),
            ("strace\t6.1-0.1", "strace\t6.2-0.1"),
            ("exit_status=78", "exit_status=0"),
            ("clock_ticks_per_second\": 100", "clock_ticks_per_second\": 1000"),
        ):
            with self.subTest(before=before):
                self.assertNotEqual(normalize(before), normalize(after))

    def test_table_pid_timing_and_order_only(self):
        a = " 14 7 99.0 python3 python3 busy\n 1 0 0.0 timeout timeout 40s\n"
        b = " 1 0 0.1 timeout timeout 40s\n 20 8 95.0 python3 python3 busy\n"
        self.assertEqual(normalize(a), normalize(b))
        self.assertNotEqual(normalize(a), normalize(b.replace("python3 busy", "python3 fixed")))

    def check_cpu(self, busy, fixed):
        with tempfile.TemporaryDirectory() as directory:
            for name, value in (("before", busy), ("after", fixed)):
                Path(directory, f"cpu-{name}.txt").write_text(json.dumps({"cpu_percent_one_core": value}))
            return subprocess.run([sys.executable, str(TOOLS / "check_cpu.py"), directory], capture_output=True, timeout=3)

    def test_cpu_oracle_accepts_contrast(self):
        self.assertEqual(self.check_cpu(90, 0).returncode, 0)

    def test_cpu_oracle_rejects_missing_fault(self):
        self.assertNotEqual(self.check_cpu(0, 0).returncode, 0)

    def test_cpu_oracle_rejects_no_recovery(self):
        self.assertNotEqual(self.check_cpu(90, 90).returncode, 0)

    def probe(self, body):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(3)

            def reply():
                connection, _ = server.accept()
                with connection:
                    connection.sendall(body)

            thread = threading.Thread(target=reply)
            thread.start()
            try:
                return subprocess.run([
                    sys.executable, str(TOOLS / "probe.py"), str(server.getsockname()[1]), "app",
                ], capture_output=True, timeout=3)
            finally:
                thread.join(timeout=4)

    def test_probe_accepts_exact_service(self):
        self.assertEqual(self.probe(b"service=app status=ok\n").returncode, 0)

    def test_open_port_with_wrong_service_is_not_recovery(self):
        result = self.probe(b"service=incumbent status=ok\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"wrong service response", result.stderr)


if __name__ == "__main__":
    unittest.main()
