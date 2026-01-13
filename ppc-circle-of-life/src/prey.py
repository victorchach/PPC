#!/usr/bin/env python3
import os
import time
import socket
import random

HOST = "127.0.0.1"
PORT = 1789

# seuils
H = 50     # faim : si energy < H -> tente de FEED
R = 75     # reproduction : si energy > R -> tente REPRO
E_GAIN = 50
E_DECAY = 5

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
    print(f"[prey] PID={pid} starting")

    state = {
        "tick": 0,
        "energy": 100,
        "active": True,
    }

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))

        # JOIN
        resp = send_line(s, f"JOIN PREY {pid}")
        print(f"[prey] env: {resp}")

        try:
            while True:
                state["tick"] += 1

                # actif/passif (simple)
                state["active"] = (random.random() < 0.6)  # 60% actif
                state["energy"] -= E_DECAY

                # mort si énergie < 0 (plus proche du sujet)
                if state["energy"] < 0:
                    resp = send_line(s, f"DIE PREY {pid}")
                    print(f"[prey] env: {resp} -> exiting (energy={state['energy']})")
                    break

                # reproduction (si actif)
                if state["active"] and state["energy"] > R:
                    resp = send_line(s, f"REPRO PREY {pid}")
                    print(f"[prey] env: {resp}")
                    # coût d'énergie optionnel (sinon reproduction infinie)
                    state["energy"] -= 10

                # feed (si actif et faim)
                if state["active"] and state["energy"] < H:
                    resp = send_line(s, f"FEED PREY {pid}")
                    print(f"[prey] env: {resp}")
                    if resp.startswith("OK"):
                        state["energy"] += E_GAIN

                time.sleep(TICK_SLEEP)

        except KeyboardInterrupt:
            print("\n[prey] KeyboardInterrupt -> exiting")
            # on peut signaler DIE si tu veux, mais pas obligatoire

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
