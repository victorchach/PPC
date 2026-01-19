#!/usr/bin/env python3
import socket
import os
import time
import signal
import sys

from shared import attach_shared, read_state, write_state

HOST = "127.0.0.1"
PORT = 5000

ENERGY_DECAY = 2
FEED_GAIN = 8
H = 15
R = 40

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
    s.send(f"JOIN PREDATOR {pid}\n".encode())

    energy = 25

    while running and energy > 0:
        energy -= ENERGY_DECAY

        if energy < H:
            grass, preys, preds, drought = read_state(shm, sem)
            if preys > 0:
                preys -= 1
                energy += FEED_GAIN
                write_state(shm, sem, grass, preys, preds, drought)

        if energy > R:
            energy //= 2

        time.sleep(1)

    grass, preys, preds, drought = read_state(shm, sem)
    preds -= 1
    write_state(shm, sem, grass, preys, preds, drought)

    s.send(f"DIE PREDATOR {pid}\n".encode())
    s.close()


if __name__ == "__main__":
    main()
