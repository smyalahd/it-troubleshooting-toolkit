import socket
import unittest
from unittest.mock import MagicMock, patch

import troubleshoot


class TroubleshootingToolkitTests(unittest.TestCase):
    def test_system_check_passes_and_contains_expected_fields(self):
        result = troubleshoot.check_system()
        self.assertEqual(result.status, "PASS")
        self.assertIn("operating_system", result.details)
        self.assertIn("python_version", result.details)

    @patch("troubleshoot.socket.getaddrinfo")
    def test_dns_success_deduplicates_addresses(self, getaddrinfo):
        getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", 0)),
        ]
        result = troubleshoot.check_dns("example.test")
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.details["addresses"], ["192.0.2.10"])

    @patch("troubleshoot.socket.getaddrinfo", side_effect=socket.gaierror("not found"))
    def test_dns_failure_is_reported(self, _mock_dns):
        result = troubleshoot.check_dns("missing.invalid")
        self.assertEqual(result.status, "FAIL")
        self.assertIn("error", result.details)

    def test_invalid_port_fails_without_network_call(self):
        result = troubleshoot.check_tcp_port("localhost", 70000)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("between 1 and 65535", result.summary)

    @patch("troubleshoot.socket.create_connection")
    def test_tcp_success(self, create_connection):
        connection = MagicMock()
        create_connection.return_value = connection
        result = troubleshoot.check_tcp_port("localhost", 443)
        self.assertEqual(result.status, "PASS")
        connection.__enter__.assert_called_once()

    @patch("troubleshoot.socket.create_connection", side_effect=ConnectionRefusedError("refused"))
    def test_tcp_refused_is_reported(self, _mock_connect):
        result = troubleshoot.check_tcp_port("localhost", 443)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("error", result.details)

    def test_report_has_expected_schema(self):
        with patch("troubleshoot.check_dns", return_value=troubleshoot.CheckResult("dns", "PASS", "ok", {})), \
             patch("troubleshoot.check_ping", return_value=troubleshoot.CheckResult("ping", "PASS", "ok", {})), \
             patch("troubleshoot.check_tcp_port", return_value=troubleshoot.CheckResult("tcp_port", "PASS", "ok", {})):
            report = troubleshoot.build_report("example.test", [443])
        self.assertEqual(report["overall_status"], "PASS")
        self.assertEqual(report["target"]["host"], "example.test")
        self.assertEqual(len(report["checks"]), 4)


if __name__ == "__main__":
    unittest.main()
