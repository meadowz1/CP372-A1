# CP372 Assignment 1 - Protocol Documentation

**Group#:** 6  **Members:** Mike Bangar, Joshua Goudy, Anson Huang, Ali Lopez, Mahi Srivastav

## 1. System Overview

The system has two programs, `server.py` and `client.py`, plus a shared
helper module `protocol.py`. They communicate over a single TCP connection
using Python's `socket` library. The server serves one client at a time,
stays running until manually stopped, and returns to waiting for a new
client when the current one disconnects.

Users identify themselves with `LOGIN` (checked against `users.txt`), then
can exchange text messages and transfer files. The server stores uploaded
files in `server_files/`; the client saves downloads in `client_downloads/`.

TCP delivers an ordered, reliable **byte stream** with no message
boundaries. The protocol therefore adds its own framing: commands and replies
are single newline-terminated lines, and file contents are sent as raw bytes
whose exact length was announced in the preceding header line.

## 2. Protocol Specification

### 2.1 General rules
- Text is UTF-8. Every command and reply is **one line** ending in `\n`.
  A trailing `\r` is ignored. Maximum line length is 8192 bytes.
- Command names are case-insensitive. Arguments are case-sensitive.
- Client -> server commands use the form `COMMAND: argument`
  (`LIST` and `QUIT` have no argument).
- Every server reply begins with `OK` (success) or `ERR <reason>` (failure).
- The client terminal accepts the friendlier form `LOGIN Alice`, which the
  client program converts to `LOGIN: Alice` on the wire.
- Except for `LOGIN` and `QUIT`, commands are rejected with
  `ERR please LOGIN first` until the client has logged in.

### 2.2 Commands

| Command | Wire syntax | Success reply | Error replies |
|---|---|---|---|
| LOGIN | `LOGIN: <name>` | `OK welcome <name>` | `ERR unknown user`, `ERR already logged in as <name>`, `ERR server user list unavailable` |
| MSG | `MSG: <text>` | `OK message received` | `ERR empty message` |
| LIST | `LIST` | `OK <n>` followed by `n` lines `<name>\t<size>` | `ERR please LOGIN first` |
| UPLOAD | `UPLOAD: <filename> <size>` | `OK READY`, then (after the bytes) `OK <size> <sha256>` | `ERR invalid filename`, `ERR file too large`, `ERR usage: ...` |
| DOWNLOAD | `DOWNLOAD: <filename>` | `OK <size> <sha256>` followed by `size` raw bytes | `ERR file not found`, `ERR invalid filename`, `ERR could not read file` |
| QUIT | `QUIT` | `OK bye`, then both sides close | - |

Any other input yields `ERR unknown command '<x>' (valid: ...)`, and a known
command written in the wrong format yields
`ERR malformed command, expected '<form>'`.

### 2.3 Message structure
```
<COMMAND>: <argument>\n         client -> server
OK[ <details>]\n                 server -> client (success)
ERR <reason>\n                   server -> client (failure)
```
Examples:
```
LOGIN: Alice            ->  OK welcome Alice
MSG: Hello Server       ->  OK message received
UPLOAD: report.pdf 48213 ->  OK READY
DOWNLOAD: report.pdf    ->  OK 48213 3a7bd3e2...
QUIT                    ->  OK bye
```

## 3. File Transfer Workflow

### Upload (client -> server)
1. Client checks that the local file exists, reads its size.
2. Client sends `UPLOAD: <filename> <size>`. (The filename may contain
   spaces; the size is the last word on the line.)
3. Server validates the filename (no `/ \ : * ? " < > |`, no `..`, no
   control characters) and size (max 1 GiB). If invalid it replies `ERR ...`
   and the client sends nothing further. Otherwise it replies `OK READY`.
4. Client streams exactly `<size>` raw bytes (64 KiB chunks, binary mode).
5. Server reads exactly `<size>` bytes into `<filename>.part`, then renames
   it to `<filename>` and replies `OK <size> <sha256>`.
6. Client compares the returned SHA-256 with the one it computed while
   sending and reports success or a checksum mismatch.

### Download (server -> client)
1. Client sends `DOWNLOAD: <filename>`.
2. Server checks the name and that the file exists. On failure: `ERR ...`.
3. Server replies `OK <size> <sha256>` and then streams exactly `<size>` raw
   bytes.
4. Client reads exactly `<size>` bytes into a `.part` file in
   `client_downloads/`, verifies the SHA-256, then renames it into place
   (or discards it on mismatch).

Because the receiver always knows the exact byte count, binary files of any
size (including empty files) are transferred correctly and the next command
on the same connection is never confused with file data.

## 4. Error Handling Rules

| Situation | Behaviour |
|---|---|
| Empty line / empty message | `ERR empty command` / `ERR empty message`; connection stays open |
| Unknown command or wrong format | `ERR unknown command ...` / `ERR malformed command ...`; connection stays open |
| Command before LOGIN | `ERR please LOGIN first` |
| Unknown user / double login | `ERR unknown user` / `ERR already logged in as ...` |
| Missing file (download) | `ERR file not found` |
| Missing local file (upload) | Client reports it and sends nothing |
| Unsafe filename (e.g. `../x`) | `ERR invalid filename` |
| Line longer than 8192 bytes | `ERR line too long`, connection closed |
| Client disconnects mid-transfer | Server deletes the partial `.part` file, logs it, and waits for the next client |
| Client silent for 300 s | Server sends `ERR idle timeout`, closes, waits for next client |
| Server not running | Client prints the error and offers to retry |
| Server closes unexpectedly | Client reports it and exits cleanly |
| Corrupted transfer | SHA-256 mismatch is reported; incomplete downloads are discarded |

Neither program should crash on any of the above; every network call is
wrapped so errors are reported to the user and logged.

## 5. Connection Termination

1. Client sends `QUIT`.
2. Server replies `OK bye`, logs "Client disconnected", and closes its
   socket for that client.
3. Client prints "Disconnected." and closes its socket.
4. Server returns to `accept()` and waits for the next client.

If either side disappears without `QUIT` (crash, Ctrl+C, network failure) the
other side detects it as a closed connection (`recv` returns no data) or a
socket error, cleans up any partial file, and carries on.

## 6. Design Decisions

- **Text-based, line-oriented commands** are easy to read, debug (even with
  `telnet`/`nc`), and document.
- **`COMMAND: argument`** matches the example messages in the assignment
  handout while keeping parsing trivial.
- **Size announced before file bytes** avoids delimiters/escaping and makes
  binary transfer safe.
- **SHA-256 (hashlib)** gives end-to-end verification that the original file
  contents were preserved.
- **Temporary `.part` files + rename** mean a half-received file is never
  mistaken for a complete one.
- **Shared `protocol.py`** keeps framing, parsing, and file I/O identical on
  both sides, and uses a buffered reader so TCP segmentation (several
  commands in one packet, or one command split across packets) cannot break
  the protocol.
- **Single-threaded server** as the handout requires; a safety net around the
  per-client loop guarantees an error with one client never stops the server.
- **Server-side filename validation** prevents path traversal outside
  `server_files/`.
- Only the allowed modules (`socket`, `os`, `time`, `hashlib`) are used.
