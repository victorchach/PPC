#!/usr/bin/env python3
import os
import time
import socket
import random

# valeurs par défaut (quand tu lances prey.py à la main)
HOST = "127.0.0.1"
PORT = 1789

H = 50
R = 75
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


def agent_main(host: str, port: int, H_: int, R_: int, e_gain: int, e_decay: int, tick_sleep: float) -> None:
    """
    La logique prey, mais paramétrable.
    -> env.py pourra lancer ça dans un nouveau process via multiprocessing.
    """
    pid = os.getpid()
    print(f"[prey] PID={pid} starting")

    state = {
        "tick": 0,
        "energy": 100,
        "active": True,
    }

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, port))
        resp = send_line(s, f"JOIN PREY {pid}")
        print(f"[prey] env: {resp}")

        try:
            while True:
                state["tick"] += 1

                state["active"] = (random.random() < 0.6)
                state["energy"] -= e_decay

                # mort
                if state["energy"] < 0:
                    resp = send_line(s, f"DIE PREY {pid}")
                    print(f"[prey] env: {resp} -> exiting (energy={state['energy']})")
                    break

                # reproduction
                if state["active"] and state["energy"] > R_:
                    resp = send_line(s, f"REPRO PREY {pid}")
                    print(f"[prey] env: {resp}")
                    state["energy"] -= 10

                # feed
                if state["active"] and state["energy"] < H_:
                    resp = send_line(s, f"FEED PREY {pid}")
                    print(f"[prey] env: {resp}")
                    if resp.startswith("OK"):
                        state["energy"] += e_gain

                time.sleep(tick_sleep)

        except KeyboardInterrupt:
            print("\n[prey] KeyboardInterrupt -> exiting")


def main() -> int:
    # quand tu lances "python3 prey.py", tu gardes le même comportement qu'avant
    agent_main(HOST, PORT, H, R, E_GAIN, E_DECAY, TICK_SLEEP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
