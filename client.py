"""
client.py - CP372 Assignment 1 TCP client.

Run:   python client.py
You will be asked for the server IP and port (press Enter for the defaults).

Commands you type (the client translates them to the wire format "CMD: arg"):
    LOGIN <name>        MSG <text>        LIST
    UPLOAD <file>       DOWNLOAD <name>   QUIT
    HELP                RAW <line>   (sends a line exactly as typed - for testing errors)
"""

import os
import socket

from protocol import Connection, ConnectionClosed, ProtocolError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "client_files")         # files we can upload
DOWNLOAD_DIR = os.path.join(BASE_DIR, "client_downloads")   # downloads land here
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9000
RESPONSE_TIMEOUT = 60   # seconds to wait for the server before giving up

HELP_TEXT = """Commands:
  LOGIN <name>      identify yourself (name must be in the server's users.txt)
  MSG <text>        send a text message to the server
  LIST              list files stored on the server
  UPLOAD <file>     upload a file (path, or a file inside client_files/)
  DOWNLOAD <name>   download a file from the server into client_downloads/
  QUIT              disconnect
  HELP              show this help
  RAW <line>        send a raw protocol line (for testing error handling)"""


def connect():
    """Ask for IP/port and connect. Returns a Connection, or None if the user gives up."""
    while True:
        host = input("Server IP [%s]: " % DEFAULT_HOST).strip() or DEFAULT_HOST
        port_text = input("Server port [%d]: " % DEFAULT_PORT).strip() or str(DEFAULT_PORT)
        if not (port_text.isascii() and port_text.isdigit() and 0 < int(port_text) < 65536):
            print("Invalid port number.")
            continue
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect((host, int(port_text)))
        except (OSError, UnicodeError) as e:
            sock.close()
            print("Could not connect to %s:%s - %s" % (host, port_text, e))
            if input("Try again? (y/n): ").strip().lower() != "y":
                return None
            continue
        sock.settimeout(RESPONSE_TIMEOUT)
        print("Connected to %s:%s" % (host, port_text))
        return Connection(sock)


def request(conn, line):
    """Send one command line, read and print the server's one-line reply."""
    conn.send_line(line)
    reply = conn.recv_line()
    print("Server: " + reply)
    return reply


def do_list(conn):
    reply = request(conn, "LIST")
    parts = reply.split()
    if len(parts) == 2 and parts[0] == "OK" and parts[1].isdigit():
        count = int(parts[1])
        for _ in range(count):
            name, _, size = conn.recv_line().partition("\t")
            print("  %-40s %s bytes" % (name, size))
        if count == 0:
            print("  (no files on server)")


def resolve_upload_path(arg):
    path = arg.strip().strip('"')
    if os.path.isfile(path):
        return path
    alt = os.path.join(UPLOAD_DIR, path)
    if os.path.isfile(alt):
        return alt
    return None


def do_upload(conn, arg):
    path = resolve_upload_path(arg)
    if path is None:
        print("Local file not found: %s (looked in current folder and client_files/)" % arg)
        return
    name = os.path.basename(path)
    size = os.path.getsize(path)

    reply = request(conn, "UPLOAD: %s %d" % (name, size))
    if reply != "OK READY":
        return                                   # server refused; nothing more to send
    print("Uploading %s (%d bytes)..." % (name, size))
    local_digest = conn.send_file(path, size)
    reply = conn.recv_line()
    parts = reply.split()
    if len(parts) == 3 and parts[0] == "OK" and parts[2] == local_digest:
        print("Server: %s\nUpload complete, checksum verified." % reply)
    elif len(parts) == 3 and parts[0] == "OK":
        print("Server: %s\nWARNING: checksum mismatch - file may be corrupted!" % reply)
    else:
        print("Server: " + reply)


def do_download(conn, name):
    conn.send_line("DOWNLOAD: " + name)
    reply = conn.recv_line()
    parts = reply.split()
    if not (len(parts) == 3 and parts[0] == "OK" and parts[1].isdigit()):
        print("Server: " + reply)                # e.g. ERR file not found
        return
    size, expected = int(parts[1]), parts[2]
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    dest = os.path.join(DOWNLOAD_DIR, os.path.basename(name))
    temp = dest + ".part"
    print("Downloading %s (%d bytes)..." % (name, size))
    digest = conn.recv_to_file(temp, size)
    if digest == expected:
        os.replace(temp, dest)
        print("Download complete: saved to %s (checksum verified)" % dest)
    else:
        os.remove(temp)
        print("ERROR: checksum mismatch, download discarded.")


def run_session(conn):
    print(HELP_TEXT)
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            line = "QUIT"
        if not line:
            print("Nothing entered. Type HELP for commands.")
            continue

        cmd, _, arg = line.partition(" ")
        cmd, arg = cmd.upper(), arg.strip()

        try:
            if cmd == "HELP":
                print(HELP_TEXT)
            elif cmd == "LOGIN":
                request(conn, "LOGIN: " + arg) if arg else print("Usage: LOGIN <name>")
            elif cmd == "MSG":
                request(conn, "MSG: " + arg) if arg else print("Usage: MSG <text>  (empty messages are not sent)")
            elif cmd == "LIST":
                do_list(conn)
            elif cmd == "UPLOAD":
                do_upload(conn, arg) if arg else print("Usage: UPLOAD <file>")
            elif cmd == "DOWNLOAD":
                do_download(conn, arg) if arg else print("Usage: DOWNLOAD <name>")
            elif cmd == "RAW":
                request(conn, arg)
            elif cmd == "QUIT":
                try:
                    request(conn, "QUIT")
                except (ConnectionClosed, OSError):
                    pass
                print("Disconnected.")
                return
            else:
                print("Unknown command '%s'. Type HELP for the list." % cmd)
        except ConnectionClosed:
            print("The server closed the connection.")
            return
        except ProtocolError as e:
            print("Protocol error from server: %s. Disconnecting." % e)
            return
        except OSError as e:
            print("Connection or file problem: %s. Disconnecting." % e)
            return


def main():
    conn = connect()
    if conn is None:
        return
    try:
        run_session(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
