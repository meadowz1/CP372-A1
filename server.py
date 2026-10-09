"""
server.py

Handles ONE client at a time (no threads). After a client disconnects (cleanly
or not) the server goes back to waiting for the next one. Stop it with Ctrl+C.

Run:   python server.py
Config (optional environment variables):  CP372_HOST, CP372_PORT
"""

import os
import socket
import time

from protocol import (Connection, ConnectionClosed, ProtocolError, MAX_FILE_SIZE,
                      hash_file, is_safe_filename, parse_command)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("CP372_HOST", "127.0.0.1")  
PORT = int(os.environ.get("CP372_PORT", "9000"))
USERS_FILE = os.path.join(BASE_DIR, "users.txt")
STORAGE_DIR = os.path.join(BASE_DIR, "server_files")
IDLE_TIMEOUT = 300 


def log(message):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), message), flush=True)


def load_users():
    """Read valid usernames from users.txt. Returns None if the file can't be read."""
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            return {ln.strip() for ln in f
                    if ln.strip() and not ln.strip().startswith("#")}
    except OSError:
        return None


class ClientSession:
    """All the state and command handlers for one connected client."""

    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.user = None

    def who(self):
        return self.user if self.user else "%s:%s" % self.addr

    # ---- main loop -------------------------------------------------------
    def run(self):
        handlers = {
            "LOGIN": self.handle_login,
            "MSG": self.handle_msg,
            "LIST": self.handle_list,
            "UPLOAD": self.handle_upload,
            "DOWNLOAD": self.handle_download,
        }
        self.conn.sock.settimeout(IDLE_TIMEOUT)
        reason = "client quit"
        try:
            while True:
                line = self.conn.recv_line()
                try:
                    cmd, arg = parse_command(line)
                except ProtocolError as e:
                    log("ERROR bad command from %s: %s" % (self.who(), e))
                    self.conn.send_line("ERR %s" % e)
                    continue

                if cmd == "QUIT":
                    self.conn.send_line("OK bye")
                    return
                if cmd != "LOGIN" and self.user is None:
                    log("ERROR %s tried %s before LOGIN" % (self.who(), cmd))
                    self.conn.send_line("ERR please LOGIN first")
                    continue
                handlers[cmd](arg)

        except ConnectionClosed:
            reason = "connection lost (client closed unexpectedly)"
        except socket.timeout:
            reason = "idle timeout"
            try:
                self.conn.send_line("ERR idle timeout, disconnecting")
            except OSError:
                pass
        except ProtocolError as e:
            reason = "protocol violation: %s" % e
            try:
                self.conn.send_line("ERR %s" % e)
            except OSError:
                pass
        except OSError as e:
            reason = "network/file error: %s" % e
        finally:
            log("Client disconnected: %s (%s)" % (self.who(), reason))

    # ---- command handlers ------------------------------------------------
    def handle_login(self, arg):
        if self.user:
            self.conn.send_line("ERR already logged in as %s" % self.user)
            return
        users = load_users()
        if users is None:
            log("ERROR could not read users.txt")
            self.conn.send_line("ERR server user list unavailable")
        elif arg in users:
            self.user = arg
            log("Login OK: %s (%s:%s)" % (arg, self.addr[0], self.addr[1]))
            self.conn.send_line("OK welcome %s" % arg)
        else:
            log("ERROR login rejected for unknown user '%s'" % arg[:30])
            self.conn.send_line("ERR unknown user")

    def handle_msg(self, arg):
        log("Message received from %s: %s" % (self.user, arg))
        self.conn.send_line("OK message received")

    def handle_list(self, _arg):
        names = []
        for name in sorted(os.listdir(STORAGE_DIR)):
            path = os.path.join(STORAGE_DIR, name)
            if (os.path.isfile(path) and is_safe_filename(name)
                    and not name.startswith(".") and not name.endswith(".part")):
                names.append((name, os.path.getsize(path)))
        self.conn.send_line("OK %d" % len(names))
        for name, size in names:
            self.conn.send_line("%s\t%d" % (name, size))
        log("File list sent to %s (%d files)" % (self.user, len(names)))

    def handle_upload(self, arg):
        # arg = "<filename> <size>"  (filename may contain spaces, so split from the right)
        name, sep, size_text = arg.rpartition(" ")
        name = name.strip()
        if not sep or not (size_text.isascii() and size_text.isdigit()):
            self.conn.send_line("ERR usage: UPLOAD: <filename> <size-in-bytes>")
            return
        size = int(size_text)
        if not is_safe_filename(name) or name.endswith(".part"):
            log("ERROR rejected upload with invalid filename from %s" % self.user)
            self.conn.send_line("ERR invalid filename")
            return
        if size > MAX_FILE_SIZE:
            self.conn.send_line("ERR file too large")
            return

        final_path = os.path.join(STORAGE_DIR, name)
        temp_path = final_path + ".part"
        self.conn.send_line("OK READY")           # client may now send `size` raw bytes
        log("Receiving '%s' (%d bytes) from %s ..." % (name, size, self.user))
        digest = self.conn.recv_to_file(temp_path, size)   # cleans up on failure
        os.replace(temp_path, final_path)
        log("File received: '%s' (%d bytes, sha256 %s...) from %s"
            % (name, size, digest[:12], self.user))
        self.conn.send_line("OK %d %s" % (size, digest))

    def handle_download(self, arg):
        if not is_safe_filename(arg):
            self.conn.send_line("ERR invalid filename")
            return
        path = os.path.join(STORAGE_DIR, arg)
        if not os.path.isfile(path) or arg.endswith(".part"):
            log("ERROR %s requested missing file '%s'" % (self.user, arg))
            self.conn.send_line("ERR file not found")
            return
        try:
            size = os.path.getsize(path)
            digest = hash_file(path)
        except OSError as e:
            log("ERROR cannot read '%s': %s" % (arg, e))
            self.conn.send_line("ERR could not read file")
            return
        self.conn.send_line("OK %d %s" % (size, digest))
        self.conn.send_file(path, size)
        log("File sent: '%s' (%d bytes) to %s" % (arg, size, self.user))


def main():
    os.makedirs(STORAGE_DIR, exist_ok=True)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
    except OSError as e:
        log("ERROR cannot bind to %s:%d - %s" % (HOST, PORT, e))
        return
    server.listen(1)
    log("Server listening on %s:%d  (Ctrl+C to stop)" % (HOST, PORT))

    try:
        while True:
            client_sock, addr = server.accept()
            log("Client connected from %s:%d" % addr)
            conn = Connection(client_sock)
            try:
                ClientSession(conn, addr).run()
            except Exception as e:            # last-resort guard: the server must not die
                log("ERROR unexpected problem with client: %r" % e)
            finally:
                conn.close()
                log("Waiting for next client...")
    except KeyboardInterrupt:
        log("Server stopped by user.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
