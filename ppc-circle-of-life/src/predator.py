#!/usr/bin/env python3
# predator.py
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

H = 50
R = 75
E_GAIN = 80
E_DECAY = 7
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
    print(f"[predator] PID={pid} starting")

    sem = sysv_ipc.Semaphore(SEM_KEY)
    shm = shared_memory.SharedMemory(name=SHM_NAME)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((host, port))
        print("[predator] env:", send_line(s, f"JOIN PREDATOR {pid}"))

        # increment predators in SHM
        sem.acquire()
        try:
            tick, predators, preys, grass, drought = unpack(shm.buf)
            predators += 1
            shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
        finally:
            sem.release()

        energy = 120

        while True:
            active = (random.random() < 0.6)
            energy -= E_DECAY

            if energy < 0:
                # die => decrement predators
                sem.acquire()
                try:
                    tick, predators, preys, grass, drought = unpack(shm.buf)
                    predators = max(0, predators - 1)
                    shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
                finally:
                    sem.release()
                print(f"[predator] died energy={energy}")
                break

            # FEED directly: eat one prey if available
            if active and energy < H:
                ate = False
                sem.acquire()
                try:
                    tick, predators, preys, grass, drought = unpack(shm.buf)
                    if preys > 0:
                        preys -= 1
                        shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
                        ate = True
                finally:
                    sem.release()

                if ate:
                    energy += E_GAIN
                    # print("[predator] ate a prey")

            # REPRO via socket
            if active and energy > R:
                resp = send_line(s, f"REPRO PREDATOR {pid}")
                # print("[predator] repro:", resp)
                energy -= 15

            time.sleep(TICK_SLEEP)

    shm.close()

def main():
    agent_main(HOST, PORT)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
