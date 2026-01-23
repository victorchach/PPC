#!/usr/bin/env python3
# prey.py
import os
import time
import socket
import random
import struct
from multiprocessing import shared_memory
import sysv_ipc

HOST = "127.0.0.1"
PORT = 1789

SHM_NAME = "circle_of_life_state"
SHM_FMT = "iiiii"  # tick, predators, preys, grass, drought
SHM_SIZE = struct.calcsize(SHM_FMT)

SEM_KEY = 222
G = 10

H = 50
R = 75
E_GAIN = 50
E_DECAY = 5
TICK_SLEEP = 0.2

def recv_line(sock):
    data = b""
    while b"\n" not in data:
        chunk = sock.recv(1024)
        if not chunk:
            return ""
        data += chunk
    return data.split(b"\n", 1)[0].decode("utf-8", errors="replace").strip()

def send_line(sock, s):
    sock.sendall((s + "\n").encode("utf-8"))
    return recv_line(sock)

def unpack(buf):
    return struct.unpack(SHM_FMT, buf[:SHM_SIZE])

def pack(tick, predators, preys, grass, drought):
    return struct.pack(SHM_FMT, tick, predators, preys, grass, drought)

def agent_main(host, port):
    pid = os.getpid()
    print(f"[prey] PID={pid} starting")

    sem = sysv_ipc.Semaphore(SEM_KEY)
    shm = shared_memory.SharedMemory(name=SHM_NAME)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, port))
        print("[prey] env:", send_line(s, f"JOIN PREY {pid}"))

        # increment population in SHM (agent does it)
        sem.acquire()
        try:
            tick, predators, preys, grass, drought = unpack(shm.buf)
            preys += 1
            shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
        finally:
            sem.release()

        energy = 100

        while True:
            active = (random.random() < 0.6)
            energy -= E_DECAY

            if energy < 0:
                # die => decrement preys in SHM
                sem.acquire()
                try:
                    tick, predators, preys, grass, drought = unpack(shm.buf)
                    preys = max(0, preys - 1)
                    shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
                finally:
                    sem.release()
                print(f"[prey] died energy={energy}")
                break

            # FEED directly from SHM
            if active and energy < H:
                sem.acquire()
                try:
                    tick, predators, preys, grass, drought = unpack(shm.buf)
                    if (not drought) and grass >= G:
                        grass -= G
                        shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
                        energy += E_GAIN
                        # debug
                        # print(f"[prey] ate grass (-{G})")
                finally:
                    sem.release()

            # REPRO via socket (env spawns; SHM population increment happens in child on JOIN)
            if active and energy > R:
                resp = send_line(s, f"REPRO PREY {pid}")
                # print("[prey] repro:", resp)
                energy -= 10

            time.sleep(TICK_SLEEP)

    shm.close()

def main():
    agent_main(HOST, PORT)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
