"""
protocol.py - helpers shared by server.py and client.py 

Wire format summary (full details in docs/PROTOCOL.md):
  * Every command and reply is ONE line of UTF-8 text ending in "\\n".
  * Client commands look like   COMMAND: argument     (LIST and QUIT take none)
  * Server replies start with   OK ...   or   ERR <reason>
  * File contents are sent as raw bytes right after a header line that
    announces the exact size, so the receiver knows when to stop reading.

Only the allowed libraries are used here: socket (via the sockets we are
given), os, hashlib.
"""

import hashlib
import os

ENCODING = "utf-8"
MAX_LINE = 8192                   # longest command/reply line we accept (bytes)
CHUNK_SIZE = 64 * 1024            # file transfer chunk size
MAX_FILE_SIZE = 1024 ** 3         # refuse uploads larger than 1 GiB

NO_ARG_COMMANDS = {"LIST", "QUIT"}
ARG_COMMANDS = {"LOGIN", "MSG", "UPLOAD", "DOWNLOAD"}
VALID_COMMANDS = ["LOGIN", "MSG", "LIST", "UPLOAD", "DOWNLOAD", "QUIT"]

_FORBIDDEN_FILENAME_CHARS = set('/\\<>:"|?*')


class ProtocolError(Exception):
    """The other side sent something that breaks the protocol rules."""


class ConnectionClosed(Exception):
    """The other side closed the TCP connection."""


# --------------------------------------------------------------------------
# Parsing / validation
# --------------------------------------------------------------------------
def parse_command(line):
    """
    Parse one client command line into (COMMAND, argument).
    Raises ProtocolError with a human-readable reason if the line is invalid.
    """
    line = line.strip()
    if not line:
        raise ProtocolError("empty command")

    head, colon, rest = line.partition(":")
    cmd = head.strip().upper()
    arg = rest.strip()

    if cmd in NO_ARG_COMMANDS:
        return cmd, arg

    if cmd in ARG_COMMANDS:
        if not colon:
            raise ProtocolError("malformed command, expected '%s: <argument>'" % cmd)
        if not arg:
            if cmd == "MSG":
                raise ProtocolError("empty message")
            raise ProtocolError("%s requires an argument" % cmd)
        return cmd, arg

    words = head.split()
    if words and words[0].upper() in (ARG_COMMANDS | NO_ARG_COMMANDS):
        first = words[0].upper()
        expected = first if first in NO_ARG_COMMANDS else first + ": <argument>"
        raise ProtocolError("malformed command, expected '%s'" % expected)

    raise ProtocolError("unknown command '%s' (valid: %s)"
                        % (head.strip()[:30], ", ".join(VALID_COMMANDS)))


def is_safe_filename(name):
    """
    True if `name` is a plain file name (no folders, no tricks like '..').
    Used on the server so a client can never read/write outside server_files/.
    """
    if not name or name in (".", "..") or len(name) > 255:
        return False
    if name != name.strip():
        return False
    for ch in name:
        if ch in _FORBIDDEN_FILENAME_CHARS or ord(ch) < 32 or ord(ch) == 127:
            return False
    return True


def hash_file(path):
    """SHA-256 hex digest of a file on disk."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Connection wrapper
# --------------------------------------------------------------------------
class Connection:
    """
    Wraps a connected TCP socket and handles the two things TCP does NOT do
    for us: message boundaries and partial reads.

    TCP is a byte STREAM: one send() on one side does not mean one recv() on
    the other. recv_line() therefore keeps an internal buffer and only returns
    when a full line has arrived; recv_to_file() keeps reading until exactly
    `size` bytes have arrived (using any bytes already in the buffer first).
    """

    def __init__(self, sock):
        self.sock = sock
        self._buf = b""

    # ---- text lines ------------------------------------------------------
    def send_line(self, text):
        text = text.replace("\r", " ").replace("\n", " ")
        self.sock.sendall(text.encode(ENCODING) + b"\n")

    def recv_line(self):
        """Return the next line (without the newline). Raises ConnectionClosed."""
        while b"\n" not in self._buf:
            if len(self._buf) > MAX_LINE:
                raise ProtocolError("line too long")
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionClosed()
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        if len(line) > MAX_LINE:
            raise ProtocolError("line too long")
        return line.decode(ENCODING, errors="replace").rstrip("\r")

    # ---- raw file bytes --------------------------------------------------
    def send_file(self, path, size):
        """Send exactly `size` bytes of the file. Returns the SHA-256 hex digest."""
        h = hashlib.sha256()
        sent = 0
        with open(path, "rb") as f:
            while sent < size:
                chunk = f.read(min(CHUNK_SIZE, size - sent))
                if not chunk:
                    raise OSError("file ended early (changed during transfer?)")
                self.sock.sendall(chunk)
                h.update(chunk)
                sent += len(chunk)
        return h.hexdigest()

    def recv_to_file(self, path, size):
        """
        Receive exactly `size` bytes and write them to `path`.
        Returns the SHA-256 hex digest. If anything goes wrong the partial
        file is deleted and the exception is re-raised.
        """
        h = hashlib.sha256()
        remaining = size
        try:
            with open(path, "wb") as f:
                while remaining > 0:
                    if self._buf:                       # leftovers from recv_line
                        chunk = self._buf[:remaining]
                        self._buf = self._buf[len(chunk):]
                    else:
                        chunk = self.sock.recv(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            raise ConnectionClosed()
                    f.write(chunk)
                    h.update(chunk)
                    remaining -= len(chunk)
        except BaseException:
            try:
                os.remove(path)
            except OSError:
                pass
            raise
        return h.hexdigest()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
