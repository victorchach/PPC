#!/usr/bin/env python3
# predator.py
import os
import time
import socket
import random
from multiprocessing import shared_memory
import struct

HOST = "127.0.0.1"
PORT = 1789

H = 50
R = 75
E_GAIN = 80
E_DECAY = 7
TICK_SLEEP = 0.2

SHM_NAME = "circle_of_life_state"
SHM_FMT = "iiiii"
SHM_SIZE = struct.calcsize(SHM_FMT)


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
    pid = os.getpid()
    print(f"[predator] PID={pid} starting")

    shm = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
            resp = send_line(s, f"JOIN PREDATOR {pid}")
            print(f"[predator] env: {resp}")

            # SHM attach (read-only snapshot)
            try:
                shm = shared_memory.SharedMemory(name=SHM_NAME)
                tick, predators, preys, grass, drought_i = struct.unpack(SHM_FMT, shm.buf[:SHM_SIZE])
                print(
                    f"[predator] shm snapshot: "
                    f"tick={tick} preys={preys} predators={predators} drought={bool(drought_i)}"
                )
            except FileNotFoundError:
                print("[predator] shm not found (env not started?)")

            energy = 120

            while True:
                active = (random.random() < 0.6)
                energy -= e_decay

                if energy < 0:
                    resp = send_line(s, f"DIE PREDATOR {pid}")
                    print(f"[predator] env: {resp} -> exiting (energy={energy})")
                    break

                if active and energy > R_:
                    resp = send_line(s, f"REPRO PREDATOR {pid}")
                    print(f"[predator] env: {resp}")
                    energy -= 15

                if active and energy < H_:
                    resp = send_line(s, f"FEED PREDATOR {pid}")
                    print(f"[predator] env: {resp}")
                    if resp.startswith("OK"):
                        energy += e_gain

                time.sleep(tick_sleep)

    except KeyboardInterrupt:
        print("\n[predator] KeyboardInterrupt -> exiting")
    finally:
        if shm is not None:
            shm.close()


def main() -> int:
    agent_main(HOST, PORT, H, R, E_GAIN, E_DECAY, TICK_SLEEP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
