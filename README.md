# CP372 Assignment 1 - TCP Client-Server File & Message App

A text-based client/server application built on the Python `socket` API. One
client at a time can log in, send messages, list files, and upload/download
files (text or binary) using a small custom application-layer protocol.

**Group:** Group# ___  
**Members:** ______, ______, ______, ______, ______

## Requirements
- Python 3.x (no third-party packages, nothing to install)
- Only these modules are used: `socket`, `os`, `time`, `hashlib`

## Folder structure
```
Group#_Assignment.1/
├── server.py            # TCP server (one client at a time)
├── client.py            # TCP client (terminal interface)
├── protocol.py          # shared helpers: line framing, file send/receive, parsing
├── users.txt            # valid usernames, one per line (used by LOGIN)
├── server_files/        # files uploaded to the server are stored here
├── client_files/        # put files here to upload them (hello.txt included)
├── client_downloads/    # files downloaded from the server are saved here
├── docs/                # protocol documentation (PDF)
└── README.md
```

## How to run the server
```
python server.py
```
The server listens on `127.0.0.1:9000` by default and runs until you press
**Ctrl+C**. After a client disconnects it waits for the next one.

To accept clients from other computers, or to change the port:
```
# Windows (PowerShell)
$env:CP372_HOST="0.0.0.0"; $env:CP372_PORT="9000"; python server.py
# macOS / Linux
CP372_HOST=0.0.0.0 CP372_PORT=9000 python server.py
```

## How to run the client
Open a second terminal in the same folder:
```
python client.py
```
Press Enter to accept the defaults (`127.0.0.1`, `9000`), or type the server's
IP address and port.

## Commands
| Type this            | What it does                                                    |
|----------------------|-----------------------------------------------------------------|
| `LOGIN Alice`        | Log in (name must be listed in `users.txt`). Required first.    |
| `MSG Hello Server`   | Send a text message; the server acknowledges it.                |
| `LIST`               | List files stored on the server.                                |
| `UPLOAD hello.txt`   | Upload a file (a path, or a file inside `client_files/`).       |
| `DOWNLOAD hello.txt` | Download a file from the server into `client_downloads/`.       |
| `QUIT`               | Disconnect gracefully.                                          |
| `HELP`               | Show the command list.                                          |
| `RAW <line>`         | Send a raw protocol line (handy to demonstrate error handling). |

### Example session
```
> LOGIN Alice
Server: OK welcome Alice
> MSG Hello Server
Server: OK message received
> UPLOAD hello.txt
Server: OK READY
Uploading hello.txt (69 bytes)...
Server: OK 69 e8ee9645...
Upload complete, checksum verified.
> LIST
Server: OK 1
  hello.txt                                69 bytes
> DOWNLOAD hello.txt
Download complete: saved to client_downloads/hello.txt (checksum verified)
> DOWNLOAD nothere.txt
Server: ERR file not found
> QUIT
Server: OK bye
```

## Error handling
Invalid/unknown commands, malformed lines, empty messages, commands before
`LOGIN`, unknown users, missing files, unsafe filenames (`../x`), server not
running, and unexpected disconnects (even mid-transfer) are all handled
without crashing either program. See `docs/` for the full protocol.

## Notes
- Files are verified end-to-end with a SHA-256 checksum on every transfer.
- Uploading a file with the same name as an existing server file replaces it.
- Valid usernames can be edited in `users.txt` (the server re-reads it on each LOGIN).
