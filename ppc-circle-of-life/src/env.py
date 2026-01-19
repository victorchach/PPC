#!/usr/bin/env python3
import sys
import socket
import select
import sysv_ipc
import signal
import time

from shared import attach_shared, read_state, write_state

HOST = "127.0.0.1"
PORT = 5000
MQ_KEY = 111
CMD_TYPE = 1

clients = {}
running = True


def handle_sigterm(sig, frame):
    global running
    running = False


signal.signal(signal.SIGTERM, handle_sigterm)


def main():
    global running

    shm, sem = attach_shared(create=True)
    write_state(shm, sem, grass=50, preys=0, predators=0, drought=0)

    mq = sysv_ipc.MessageQueue(MQ_KEY, sysv_ipc.IPC_CREAT)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()
    server.setblocking(False)

    print("[env] started")

    while running:
        # grass growth
        grass, preys, preds, drought = read_state(shm, sem)
        if not drought:
            grass += 1
            write_state(shm, sem, grass, preys, preds, drought)

        # handle sockets
        rlist, _, _ = select.select([server] + list(clients), [], [], 0.1)

        for s in rlist:
            if s is server:
                conn, _ = server.accept()
                conn.setblocking(False)
                clients[conn] = None
            else:
                data = s.recv(1024)
                if not data:
                    s.close()
                    clients.pop(s)
                    continue

                msg = data.decode().strip()
                parts = msg.split()
                cmd, kind, pid = parts[0], parts[1], int(parts[2])

                grass, preys, preds, drought = read_state(shm, sem)

                if cmd == "JOIN":
                    if kind == "PREY":
                        preys += 1
                    else:
                        preds += 1

                elif cmd == "DIE":
                    if kind == "PREY":
                        preys -= 1
                    else:
                        preds -= 1

                write_state(shm, sem, grass, preys, preds, drought)
                s.send(b"OK\n")

        # handle display commands
        try:
            msg, _ = mq.receive(type=CMD_TYPE, block=False)
            pid, action = msg.decode().split(maxsplit=1)
            pid = int(pid)

            grass, preys, preds, drought = read_state(shm, sem)

            if action == "STATUS":
                reply = f"grass={grass} preys={preys} predators={preds} drought={bool(drought)}"

            elif action == "ADD_PREY":
                reply = "start prey manually"

            elif action == "ADD_PREDATOR":
                reply = "start predator manually"

            elif action == "ADD_DROUGHT":
                drought = 1
                write_state(shm, sem, grass, preys, preds, drought)
                reply = "drought started"

            elif action == "QUIT":
                reply = "env stopping"
                running = False

            else:
                reply = "unknown command"

            mq.send(reply.encode(), type=pid)

        except sysv_ipc.BusyError:
            pass

    server.close()
    mq.remove()
    shm.remove()
    sem.remove()
    print("[env] stopped")


if __name__ == "__main__":
    main()
