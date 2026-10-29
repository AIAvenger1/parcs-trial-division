import socket


def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    address, port = s.getsockname()
    s.close()
    return port


def get_ip():
    # Pure-socket replacement for the original netifaces-based lookup
    # (netifaces has no wheels for py2.7/arm64 and needs gcc to build).
    # Opening a UDP "connection" does not send anything, it only picks
    # the interface the kernel would route through.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()
