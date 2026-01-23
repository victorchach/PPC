#!/usr/bin/env python3
# env.py
import os
import sys
import time
import socket
import select
import signal
import struct
import multiprocessing as mp
from multiprocessing import shared_memory

import sysv_ipc

# -----------------------
# CONFIG
# -----------------------
HOST = "127.0.0.1"
PORT = 1789

MQ_KEY = 111
CMD_TYPE = 1

SEM_KEY = 222   # semaphore pour protéger SHM (accessible à tous)

TICK_SLEEP = 0.2
GRASS_GROWTH = 1
G = 10

DROUGHT_DURATION = 20
DEBUG = True

# -----------------------
# SHARED MEMORY
# -----------------------
SHM_NAME = "circle_of_life_state"
# tick, predators, preys, grass, drought(0/1)
SHM_FMT = "iiiii"
SHM_SIZE = struct.calcsize(SHM_FMT)

# -----------------------
# Helpers SHM + Semaphore
# -----------------------
def shm_unpack(buf):
    return struct.unpack(SHM_FMT, buf[:SHM_SIZE])

def shm_pack(tick, predators, preys, grass, drought):
    return struct.pack(SHM_FMT, tick, predators, preys, grass, drought)

class ShmGuard:
    """Context manager: semaphore lock around shared memory operations."""
    def __init__(self, sem):
        self.sem = sem

    def __enter__(self):
        self.sem.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.sem.release()
        return False

# -----------------------
# Reproduction registry (env only)
# -----------------------
repro_ready = {"PREY": set(), "PREDATOR": set()}

# Drought internal counter (env only)
drought_tick = 0

# Globals set in main
shm = None
sem = None

def handle_drought_signal(signum, frame):
    """SIGUSR1 => start drought (set drought=1 in SHM)"""
    global drought_tick, shm, sem
    with ShmGuard(sem):
        tick, predators, preys, grass, drought = shm_unpack(shm.buf)
        # start drought
        drought = 1
        drought_tick = 0
        shm.buf[:SHM_SIZE] = shm_pack(tick, predators, preys, grass, drought)
    print("[env] drought started (signal)")

def encode_line(s):
    return (s + "\n").encode("utf-8")

def decode_bytes(b):
    return b.decode("utf-8", errors="replace")

def parse_line(line):
    # Expected: "<CMD> <KIND> <PID>"
    parts = line.strip().split()
    if len(parts) != 3:
        raise ValueError("expected 3 tokens: CMD KIND PID")
    cmd = parts[0].upper()
    kind = parts[1].upper()
    pid = int(parts[2])
    if cmd not in ("JOIN", "REPRO"):
        raise ValueError("cmd must be JOIN or REPRO")
    if kind not in ("PREY", "PREDATOR"):
        raise ValueError("kind must be PREY or PREDATOR")
    return cmd, kind, pid

def run_prey_proc(host, port):
    from prey import agent_main
    agent_main(host, port)

def run_predator_proc(host, port):
    from predator import agent_main
    agent_main(host, port)

def spawn_prey(children):
    p = mp.Process(target=run_prey_proc, args=(HOST, PORT), daemon=True)
    p.start()
    children.append(p)
    return p.pid

def spawn_predator(children):
    p = mp.Process(target=run_predator_proc, args=(HOST, PORT), daemon=True)
    p.start()
    children.append(p)
    return p.pid

def handle_display_command(mq, children, cmd):
    """
    cmd format: "<PID> <ACTION>"
    ACTION: STATUS | QUIT | ADD_PREY | ADD_PREDATOR | ADD_DROUGHT
    """
    cmd = cmd.strip()
    parts = cmd.split(maxsplit=1)
    if len(parts) != 2:
        return 1

    sender_pid_str, action = parts[0], parts[1].upper()
    try:
        sender_pid = int(sender_pid_str)
    except ValueError:
        return 1

    if action == "STATUS":
        with ShmGuard(sem):
            tick, predators, preys, grass, drought = shm_unpack(shm.buf)
        payload = f"tick={tick} predators={predators} preys={preys} grass={grass} drought={bool(drought)}"
        mq.send(payload.encode("utf-8"), type=sender_pid)
        return 1

    if action == "QUIT":
        mq.send(b"OK quitting", type=sender_pid)
        return 0

    if action == "ADD_PREY":
        new_pid = spawn_prey(children)
        mq.send(f"OK spawned prey pid={new_pid}".encode("utf-8"), type=sender_pid)
        return 1

    if action == "ADD_PREDATOR":
        new_pid = spawn_predator(children)
        mq.send(f"OK spawned predator pid={new_pid}".encode("utf-8"), type=sender_pid)
        return 1

    if action == "ADD_DROUGHT":
        # on déclenche bien un signal (comme demandé dans le sujet)
        signal.raise_signal(signal.SIGUSR1)
        mq.send(b"OK drought signaled", type=sender_pid)
        return 1

    mq.send(f"ERR unknown action {action}".encode("utf-8"), type=sender_pid)
    return 1

def main():
    global shm, sem, drought_tick

    print(f"[env] PID={os.getpid()} starting")

    # MQ
    mq = sysv_ipc.MessageQueue(MQ_KEY, sysv_ipc.IPC_CREAT)
    print(f"[env] MessageQueue created key={MQ_KEY}")

    # Semaphore (SysV) for SHM
    sem = sysv_ipc.Semaphore(SEM_KEY, sysv_ipc.IPC_CREAT, initial_value=1)
    print(f"[env] Semaphore created key={SEM_KEY}")

    # Shared memory init
    try:
        old = shared_memory.SharedMemory(name=SHM_NAME, create=False)
        old.close()
        old.unlink()
    except FileNotFoundError:
        pass

    shm = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)

    with ShmGuard(sem):
        shm.buf[:SHM_SIZE] = shm_pack(0, 0, 0, 100, 0)

    # Signal
    signal.signal(signal.SIGUSR1, handle_drought_signal)

    # Socket server for JOIN/REPRO
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(50)
    server.setblocking(False)
    print(f"[env] socket listening {HOST}:{PORT}")

    children = []
    clients = set()
    recv_buf = {}

    running = True
    try:
        while running:
            # ---- global tick & grass growth & drought duration ----
            with ShmGuard(sem):
                tick, predators, preys, grass, drought = shm_unpack(shm.buf)
                tick += 1

                if drought:
                    drought_tick += 1
                    if drought_tick >= DROUGHT_DURATION:
                        drought = 0
                        drought_tick = 0
                        print("[env] drought ended")
                else:
                    grass += GRASS_GROWTH

                shm.buf[:SHM_SIZE] = shm_pack(tick, predators, preys, grass, drought)

            # ---- display MQ ----
            try:
                raw, _t = mq.receive(type=CMD_TYPE, block=False)
                cmd = decode_bytes(raw)
                keep = handle_display_command(mq, children, cmd)
                if keep == 0:
                    running = False
            except sysv_ipc.BusyError:
                pass

            # ---- socket multiplexing ----
            rlist = [server] + list(clients)
            readable, _, exceptional = select.select(rlist, [], rlist, 0)

            if server in readable:
                while True:
                    try:
                        cs, addr = server.accept()
                        cs.setblocking(False)
                        clients.add(cs)
                        recv_buf[cs] = ""
                        if DEBUG:
                            print(f"[env] accepted {addr}")
                    except BlockingIOError:
                        break

            for cs in list(clients):
                if cs not in readable:
                    continue
                try:
                    data = cs.recv(4096)
                except (BlockingIOError, InterruptedError):
                    continue
                except ConnectionResetError:
                    clients.remove(cs)
                    recv_buf.pop(cs, None)
                    cs.close()
                    continue

                if not data:
                    clients.remove(cs)
                    recv_buf.pop(cs, None)
                    cs.close()
                    continue

                recv_buf[cs] += decode_bytes(data)

                while "\n" in recv_buf[cs]:
                    line, rest = recv_buf[cs].split("\n", 1)
                    recv_buf[cs] = rest
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        cmd, kind, pid = parse_line(line)
                    except Exception as e:
                        cs.sendall(encode_line(f"ERR {e}"))
                        continue

                    if cmd == "JOIN":
                        # JOIN: agent increments its own population in SHM (agent-side)
                        cs.sendall(encode_line("OK JOIN"))
                        if DEBUG:
                            print(f"[env] JOIN {kind} pid={pid}")
                        continue

                    if cmd == "REPRO":
                        repro_ready[kind].add(pid)
                        if len(repro_ready[kind]) >= 2:
                            p1 = repro_ready[kind].pop()
                            p2 = repro_ready[kind].pop()
                            if kind == "PREY":
                                new_pid = spawn_prey(children)
                                cs.sendall(encode_line(f"OK BIRTH PREY pid={new_pid} parents=({p1},{p2})"))
                                print(f"[env] birth PREY pid={new_pid} parents=({p1},{p2})")
                            else:
                                new_pid = spawn_predator(children)
                                cs.sendall(encode_line(f"OK BIRTH PREDATOR pid={new_pid} parents=({p1},{p2})"))
                                print(f"[env] birth PREDATOR pid={new_pid} parents=({p1},{p2})")
                        else:
                            cs.sendall(encode_line("OK REPRO WAITING"))
                        continue

            for cs in exceptional:
                if cs is server:
                    continue
                if cs in clients:
                    clients.remove(cs)
                recv_buf.pop(cs, None)
                try:
                    cs.close()
                except Exception:
                    pass

            time.sleep(TICK_SLEEP)

    except KeyboardInterrupt:
        print("\n[env] KeyboardInterrupt")

    finally:
        # cleanup sockets
        for cs in list(clients):
            try:
                cs.close()
            except Exception:
                pass
        try:
            server.close()
        except Exception:
            pass

        # cleanup children
        for p in children:
            if p.is_alive():
                p.terminate()
        for p in children:
            p.join(timeout=1)

        # MQ remove
        try:
            mq.remove()
        except Exception:
            pass

        # SHM remove
        try:
            shm.close()
            shm.unlink()
        except Exception:
            pass

        # Semaphore remove
        try:
            sem.remove()
        except Exception:
            pass

        print("[env] stopped")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
