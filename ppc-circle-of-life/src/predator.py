#!/usr/bin/env python3
import os
import time
import socket
import random

HOST = "127.0.0.1"
PORT = 1789

H = 50
R = 75
E_GAIN = 80
E_DECAY = 7

TICK_SLEEP = 0.2


def recv_line(sock: socket.socket) -> str:
    data = b""
    while b"\n" not in data:
        chunk = sock.recv(1024)
        if not chunk:
            return ""
        data += chunk
    return data.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()


def send_line(sock: socket.socket, s: str) -> str:
    sock.sendall((s + "\n").encode("utf-8"))
    return recv_line(sock)


def main() -> int:
    pid = os.getpid()
    print(f"[predator] PID={pid} starting")

    state = {
        "tick": 0,
        "energy": 120,
        "active": True,
    }

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))

        resp = send_line(s, f"JOIN PREDATOR {pid}")
        print(f"[predator] env: {resp}")

        try:
            while True:
                state["tick"] += 1

                state["active"] = (random.random() < 0.6)
                state["energy"] -= E_DECAY

                if state["energy"] < 0:
                    resp = send_line(s, f"DIE PREDATOR {pid}")
                    print(f"[predator] env: {resp} -> exiting (energy={state['energy']})")
                    break

                if state["active"] and state["energy"] > R:
                    resp = send_line(s, f"REPRO PREDATOR {pid}")
                    print(f"[predator] env: {resp}")
                    state["energy"] -= 15

                if state["active"] and state["energy"] < H:
                    resp = send_line(s, f"FEED PREDATOR {pid}")
                    print(f"[predator] env: {resp}")
                    if resp.startswith("OK"):
                        state["energy"] += E_GAIN

                time.sleep(TICK_SLEEP)

        except KeyboardInterrupt:
            print("\n[predator] KeyboardInterrupt -> exiting")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
