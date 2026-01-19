#!/usr/bin/env python3
import socket
import os
import time
import signal
import sys

from shared import attach_shared, read_state, write_state

HOST = "127.0.0.1"
PORT = 5000

ENERGY_DECAY = 1
FEED_GAIN = 5
H = 10
R = 30

running = True


def handle_sigterm(sig, frame):
    global running
    running = False


signal.signal(signal.SIGTERM, handle_sigterm)


def main():
    pid = os.getpid()
    shm, sem = attach_shared()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT))
    s.send(f"JOIN PREY {pid}\n".encode())

    energy = 20

    while running and energy > 0:
        energy -= ENERGY_DECAY

        if energy < H:
            grass, preys, preds, drought = read_state(shm, sem)
            if grass > 0 and not drought:
                grass -= 1
                energy += FEED_GAIN
                write_state(shm, sem, grass, preys, preds, drought)

        if energy > R:
            energy //= 2

        time.sleep(1)

    grass, preys, preds, drought = read_state(shm, sem)
    preys -= 1
    write_state(shm, sem, grass, preys, preds, drought)

    s.send(f"DIE PREY {pid}\n".encode())
    s.close()


if __name__ == "__main__":
    main()
