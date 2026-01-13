#!/usr/bin/env python3
import socket
import time
import os

HOST = "127.0.0.1"
PORT = 1789

def main() -> int:
    print(f"[prey] PID={os.getpid()} joining...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        s.sendall(b"JOIN PREY")
        resp = s.recv(1024)
        print("[prey] env response:", resp.decode("utf-8", errors="replace").strip())

    time.sleep(2)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())


#globalement les même explications que pour predator donc easy