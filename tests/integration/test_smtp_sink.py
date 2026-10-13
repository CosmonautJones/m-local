from email.message import EmailMessage
import os
from pathlib import Path
import socket
import smtplib
import ssl
import tempfile
import unittest
from unittest.mock import patch

from smtp_sink import FIXTURE_RECIPIENT, SmtpSink, find_openssl


class SmtpSinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not find_openssl():
            raise RuntimeError("OpenSSL is required for the SMTP fixture tests")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.recipient = FIXTURE_RECIPIENT
        self.sink = SmtpSink(Path(self.directory.name) / "smtp")
        self.sink.allow(self.recipient)

    def tearDown(self):
        if hasattr(self, "sink"):
            self.sink.close()
        self.directory.cleanup()

    def tls_context(self):
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(self.sink.ca_file), "SSL_CERT_DIR": ""}):
            context = ssl.create_default_context()
        context.verify_flags |= ssl.VERIFY_X509_STRICT
        return context

    def login(self, client):
        client.ehlo()
        client.starttls(context=self.tls_context())
        client.ehlo()
        self.assertIn("plain", client.esmtp_features["auth"].lower())
        client.login(self.sink.username, self.sink.password)

    def message(self, code="123456", recipient=None):
        message = EmailMessage()
        message["From"], message["To"] = self.sink.sender, recipient or self.recipient
        message["Subject"] = "Fixture verification message"
        message.set_content(f"Your M-Local code is: {code}\n")
        return message

    def test_starttls_strict_auth_send_and_capture(self):
        with smtplib.SMTP(self.sink.host, self.sink.port, timeout=5) as client:
            self.login(client)
            self.assertEqual(client.send_message(self.message("654321")), {})
        self.assertEqual(self.sink.take_code(self.recipient), "654321")
        self.assertEqual(self.sink.count(), 1)

    def test_bad_login_is_rejected(self):
        with smtplib.SMTP(self.sink.host, self.sink.port, timeout=5) as client:
            client.ehlo()
            client.starttls(context=self.tls_context())
            client.ehlo()
            with self.assertRaises(smtplib.SMTPAuthenticationError) as error:
                client.login(self.sink.username, "wrong-fictional-password")
            self.assertEqual(error.exception.smtp_code, 535)
        self.assertEqual(self.sink.count(), 0)

    def test_tls_is_required_before_auth_and_mail(self):
        with smtplib.SMTP(self.sink.host, self.sink.port, timeout=5) as client:
            client.ehlo()
            code, _ = client.docmd("AUTH", "PLAIN")
            self.assertEqual(code, 538)
            code, _ = client.mail(self.sink.sender)
            self.assertEqual(code, 530)
        self.assertEqual(self.sink.count(), 0)

    def test_nonfixture_sender_and_recipient_are_rejected(self):
        with smtplib.SMTP(self.sink.host, self.sink.port, timeout=5) as client:
            self.login(client)
            code, _ = client.mail("other-sender@example.test")
            self.assertEqual(code, 550)
            client.rset()
            code, _ = client.mail(self.sink.sender)
            self.assertEqual(code, 250)
            code, _ = client.rcpt("other-recipient@example.test")
            self.assertEqual(code, 550)
        self.assertEqual(self.sink.count(), 0)

    def test_oversized_data_is_rejected(self):
        payload = "Subject: fixture\r\n\r\n" + ("x" * 100 + "\r\n") * 81
        with smtplib.SMTP(self.sink.host, self.sink.port, timeout=5) as client:
            self.login(client)
            client.mail(self.sink.sender)
            client.rcpt(self.recipient)
            code, _ = client.data(payload)
            self.assertEqual(code, 552)
        self.assertEqual(self.sink.count(), 0)

    def test_private_path_must_be_fresh_absolute_leaf(self):
        with self.assertRaises(ValueError):
            SmtpSink(Path(self.directory.name))

    def test_close_cleans_idle_tls_connection_and_private_leaf(self):
        client = smtplib.SMTP(self.sink.host, self.sink.port, timeout=5)
        client.ehlo()
        client.starttls(context=self.tls_context())
        private_path, port = self.sink.private_path, self.sink.port
        self.sink.close()
        self.assertTrue(self.sink.closed)
        self.assertFalse(self.sink._thread.is_alive())
        self.assertFalse(self.sink._server.active)
        self.assertFalse(self.sink._server.threads)
        self.assertFalse(private_path.exists())
        with self.assertRaises((smtplib.SMTPServerDisconnected, OSError, socket.timeout)):
            client.noop()
        client.close()
        with self.assertRaises((ConnectionRefusedError, OSError, socket.timeout)):
            socket.create_connection((self.sink.host, port), timeout=1)


if __name__ == "__main__":
    unittest.main()
