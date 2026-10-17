"""One bounded TCP connection, with exact application-identity verification."""
import errno
import socket
import sys

port = int(sys.argv[1])
expected = f"service={sys.argv[2]} status=ok\n".encode()
try:
    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
        chunks = []
        while chunk := connection.recv(256):
            chunks.append(chunk)
            if sum(map(len, chunks)) > 1024:
                raise SystemExit("FAIL: response exceeded lab limit")
        actual = b"".join(chunks)
except OSError as error:
    print(f"CONNECT 127.0.0.1:{port} failed: errno={error.errno} {errno.errorcode.get(error.errno, 'UNKNOWN')}")
    raise SystemExit(2)
print(f"CONNECT 127.0.0.1:{port} response={actual.decode('ascii').rstrip()}")
if actual != expected:
    raise SystemExit("FAIL: wrong service response")
