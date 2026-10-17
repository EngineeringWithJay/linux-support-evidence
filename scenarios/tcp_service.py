"""Tiny loopback TCP fixture, not an HTTP or production application server."""
import errno
import signal
import socket
import sys

name, raw_port = sys.argv[1:]
port = int(raw_port)


def stop(_signal, _frame):
    print(f"STOPPED service={name} signal=SIGTERM", flush=True)
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
with socket.socket() as listener:
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", port))
    except OSError as error:
        print(f"ERROR service={name} bind=127.0.0.1:{port} errno={error.errno} {errno.errorcode[error.errno]}", flush=True)
        raise SystemExit(78)
    listener.listen(8)
    print(f"READY service={name} listen=127.0.0.1:{port}", flush=True)
    while True:
        connection, _ = listener.accept()
        with connection:
            connection.sendall(f"service={name} status=ok\n".encode())
