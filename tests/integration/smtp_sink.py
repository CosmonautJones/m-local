"""Small, bounded STARTTLS SMTP sink for the local onboarding proof."""

import base64
from collections import defaultdict, deque
from email import policy
from email.parser import BytesParser
import os
from pathlib import Path
import re
import shutil
import socket
import socketserver
import ssl
import subprocess
import threading
import time

HOST = "127.0.0.1"
FIXTURE_USERNAME = "fixture-smtp-user"
FIXTURE_PASSWORD = "fixture-smtp-password"
FIXTURE_RECIPIENT = "fixture-recipient@example.test"
FIXTURE_SENDER = "fixture-sender@example.test"
_COMMAND_LIMIT, _LINE_LIMIT = 100, 2048
_DATA_LIMIT, _SOCKET_TIMEOUT = 8192, 5.0
_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_OPENSSL = (Path("C:/Program Files/Git/usr/bin/openssl.exe"),
            Path("C:/Program Files/OpenSSL-Win64/bin/openssl.exe"),
            Path("C:/Program Files/OpenSSL/bin/openssl.exe"))


def find_openssl():
    path = shutil.which("openssl")
    return path or next((str(p) for p in _OPENSSL if p.is_file()), None)


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address, daemon_threads, block_on_close = True, True, False
    def __init__(self, sink, context):
        self.sink, self.context = sink, context
        self.active, self.threads = set(), set()
        self.lock, self.closing = threading.Lock(), False
        super().__init__((HOST, 0), _Handler)
    @staticmethod
    def close_socket(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()
    def register(self, sock):
        with self.lock:
            if self.closing:
                self.close_socket(sock)
                return False
            self.active.add(sock)
            self.threads.add(threading.current_thread())
            return True
    def replace(self, old, new):
        with self.lock:
            self.active.discard(old)
            if self.closing:
                self.close_socket(new)
                return False
            self.active.add(new)
            return True
    def unregister(self, sock):
        with self.lock:
            self.active.discard(sock)
            self.threads.discard(threading.current_thread())
    def begin_close(self):
        with self.lock:
            self.closing, active = True, tuple(self.active)
        for sock in active:
            self.close_socket(sock)
    handle_error = lambda *_: None


class _Handler(socketserver.BaseRequestHandler):
    def setup(self):
        self.sock = self.request
        self.sock.settimeout(_SOCKET_TIMEOUT)
        if not self.server.register(self.sock):
            raise OSError("server closing")
        self.reader = self.sock.makefile("rb")
        self.tls = self.authenticated = False
        self.mail_from = self.recipient = None
    def finish(self):
        self.server.unregister(self.sock)
        try:
            self.reader.close()
            self.sock.close()
        except OSError:
            pass
    def reply(self, code):
        self.sock.sendall(f"{code}\r\n".encode("ascii"))

    def line(self):
        line = self.reader.readline(_LINE_LIMIT + 1)
        if not line or len(line) > _LINE_LIMIT or not line.endswith(b"\n"):
            raise OSError
        return line

    @staticmethod
    def path(argument, verb):
        match = re.fullmatch(rf"{verb}:<([^>\r\n\x00]+)>(?: SIZE=\d+)?", argument, re.I)
        return match.group(1) if match else None
    def ehlo(self):
        self.sock.sendall(b"250-localhost\r\n250-" +
            (b"AUTH PLAIN" if self.tls else b"STARTTLS") + b"\r\n250 SIZE 8192\r\n")
    def starttls(self):
        if self.tls:
            self.reply(503); return
        self.reply(220)
        try:
            self.reader.close()
            wrapped = self.server.context.wrap_socket(self.sock, server_side=True)
            wrapped.settimeout(_SOCKET_TIMEOUT)
        except (OSError, ssl.SSLError):
            raise OSError from None
        if not self.server.replace(self.sock, wrapped):
            raise OSError
        self.sock, self.reader, self.tls = wrapped, wrapped.makefile("rb"), True
        self.authenticated = False; self.mail_from = self.recipient = None

    def auth(self, argument):
        if not self.tls:
            self.reply(538); return
        if argument.split(" ", 1)[0].upper() != "PLAIN":
            self.reply(504); return
        value = argument[5:].strip()
        if not value:
            self.reply(334)
            value = self.line().strip()
        sink = self.server.sink
        try:
            valid = len(value) <= 512 and base64.b64decode(value, validate=True) == (
                b"\x00" + sink.username.encode() + b"\x00" + sink.password.encode())
        except (TypeError, ValueError):
            valid = False
        if not valid:
            self.reply(535); return
        self.authenticated = True
        self.reply(235)

    def data(self):
        if not self.tls or not self.authenticated:
            self.reply(530); return
        self.reply(354)
        body, total = bytearray(), 0
        while True:
            line = self.line()
            if line in (b".\r\n", b".\n"):
                break
            if line.startswith(b".."):
                line = line[1:]
            total += len(line)
            if total <= _DATA_LIMIT:
                body.extend(line)
            if total > _DATA_LIMIT * 2:
                raise OSError("SMTP data limit")
        if total > _DATA_LIMIT:
            self.reply(552); return
        try:
            message = BytesParser(policy=policy.default).parsebytes(body)
            plain = message.get_body(preferencelist=("plain",))
            matches = _CODE.findall(plain.get_content() if plain else message.get_content())
        except Exception:
            matches = ()
        if len(matches) != 1:
            self.reply(550); return
        self.server.sink._record(self.recipient, matches[0])
        self.reply(250)
        self.mail_from = self.recipient = None

    def handle(self):
        try:
            self.reply(220)
            for _ in range(_COMMAND_LIMIT):
                line = self.line().decode("ascii").rstrip("\r\n")
                command, _, argument = line.partition(" ")
                command, argument = command.upper(), argument.strip()
                sink = self.server.sink
                if command == "EHLO":
                    self.ehlo()
                elif command == "STARTTLS":
                    self.starttls()
                elif command == "AUTH":
                    self.auth(argument)
                elif command in ("MAIL", "RCPT"):
                    if not self.tls or not self.authenticated:
                        self.reply(530)
                    elif command == "MAIL":
                        sender = self.path(argument, "FROM")
                        if sender is None or sender.lower() != sink.sender:
                            self.reply(550)
                        else:
                            self.mail_from, self.recipient = True, None
                            self.reply(250)
                    elif self.mail_from is None:
                        self.reply(503)
                    else:
                        recipient = self.path(argument, "TO")
                        if recipient is None or not sink.allowed(recipient):
                            self.reply(550)
                        else:
                            self.recipient = recipient
                            self.reply(250)
                elif command == "DATA":
                    if self.mail_from is None or self.recipient is None:
                        self.reply(503); continue
                    self.data()
                elif command == "RSET":
                    self.mail_from = self.recipient = None; self.reply(250)
                elif command == "NOOP":
                    self.reply(250)
                elif command == "QUIT":
                    self.reply(221)
                    return
                else:
                    self.reply(502)
        except (UnicodeError, OSError, ssl.SSLError):
            return


def _certificate(directory):
    openssl = find_openssl()
    if not openssl:
        raise RuntimeError("OpenSSL is required for the SMTP fixture")
    config = directory / "openssl.cnf"
    config.write_text("[req]\ndistinguished_name=dn\nx509_extensions=server\nprompt=no\n"
                      "[dn]\nCN=localhost\n[server]\n"
        "basicConstraints=critical,CA:TRUE\n"
                      "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\n"
                      "extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\n"
        "authorityKeyIdentifier=keyid\n"
                      "subjectAltName=DNS:localhost,IP:127.0.0.1\n", encoding="ascii")
    key, certificate = directory / "fixture-key.pem", directory / "fixture-cert.pem"
    result = subprocess.run(
        [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-sha256",
         "-keyout", os.fspath(key), "-out", os.fspath(certificate), "-config", os.fspath(config)],
        capture_output=True, timeout=15, stdin=subprocess.DEVNULL)
    if result.returncode or not key.is_file() or not certificate.is_file():
        raise RuntimeError("OpenSSL could not create the fixture certificate")
    os.chmod(key, 0o600)
    return certificate, key


class SmtpSink:
    def __init__(self, private_path):
        self.username, self.password, self.sender, self.host = (
            FIXTURE_USERNAME, FIXTURE_PASSWORD, FIXTURE_SENDER, HOST)
        self._messages, self._count = defaultdict(deque), 0
        self._condition, self._allowed, self.closed = threading.Condition(), set(), False
        path = Path(private_path).expanduser()
        if not path.is_absolute() or path.exists() or path.is_symlink():
            raise ValueError("SMTP fixture private path must be a fresh absolute leaf")
        self.private_path, self._parent = path.resolve(), path.parent.resolve()
        if self.private_path.parent != self._parent or self.private_path == self._parent:
            raise ValueError("SMTP fixture private path must be a child of its existing parent")
        self.private_path.mkdir()
        directory_stat = self.private_path.stat()
        self._directory_identity = directory_stat.st_dev, directory_stat.st_ino
        try:
            os.chmod(self.private_path, 0o700)
            self.ca_file, key = _certificate(self.private_path)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(os.fspath(self.ca_file), os.fspath(key))
            self._server = _Server(self, context)
            self.port = self._server.server_address[1]
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
        except Exception:
            try:
                self._remove_private()
            except OSError:
                pass
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def allow(self, recipient):
        if not recipient or any(c in recipient for c in "\r\n\x00"):
            raise ValueError("SMTP fixture recipient must be single-line")
        self._allowed.add(recipient.lower())

    def allowed(self, recipient):
        return recipient.lower() in self._allowed

    def _record(self, recipient, code):
        with self._condition:
            self._messages[recipient.lower()].append(code)
            self._count += 1
            self._condition.notify_all()

    def count(self):
        with self._condition:
            return self._count

    def take_code(self, recipient, timeout=5):
        if not self.allowed(recipient) or timeout < 0 or timeout > 30:
            raise ValueError("SMTP fixture recipient or wait is invalid")
        recipient, deadline = recipient.lower(), time.monotonic() + timeout
        with self._condition:
            while not self._messages.get(recipient):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Timed out waiting for the fixture code")
                self._condition.wait(remaining)
            return self._messages[recipient].popleft()

    def _remove_private(self):
        path = self.private_path
        current = path.stat() if path.exists() and not path.is_symlink() else None
        if (current is None or (current.st_dev, current.st_ino) != self._directory_identity or
                path.is_symlink() or not path.is_dir() or path.resolve() != path or
                path.parent != self._parent):
            raise OSError("SMTP fixture private path ownership check failed")
        shutil.rmtree(path)

    def close(self):
        if self.closed:
            return
        self._server.begin_close()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        if self._thread.is_alive():
            raise RuntimeError("SMTP fixture server thread did not stop")
        deadline = time.monotonic() + 2
        while self._server.active or self._server.threads:
            if time.monotonic() >= deadline:
                raise RuntimeError("SMTP fixture handler teardown did not finish")
            time.sleep(0.01)
        self._remove_private()
        self.closed = True
