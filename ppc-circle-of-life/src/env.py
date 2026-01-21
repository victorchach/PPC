#!/usr/bin/env python3
# env.py
import os
import sys
import time
import socket
import select
import signal
import random
from typing import Dict, Tuple
import multiprocessing as mp
from multiprocessing import shared_memory, Lock
import struct

import sysv_ipc  # imposée par le cours/projet (System V MQ)

# -----------------------
# CONFIG
# -----------------------
MQ_KEY = 111
CMD_TYPE = 1

HOST = "127.0.0.1"
PORT = 1789

DROUGHT_DURATION = 20
G = 10
TICK_SLEEP = 0.2

# Taux de réussite de reproduction
PREY_REPRO_SUCCESS_RATE = 2/3
PREDATOR_REPRO_SUCCESS_RATE = 1/3

DEBUG = True

shm = None  # Variable globale pour la shared memory
lock = None  # Variable globale pour le lock
# -----------------------
# SHARED MEMORY
# -----------------------
SHM_NAME = "circle_of_life_state"
SHM_FMT = "iiiii"  # tick, predators, preys, grass, drought(0/1)
SHM_SIZE = struct.calcsize(SHM_FMT)

# -----------------------
# STATE GLOBAL
# -----------------------
state = {
    "tick": 0,
    "predators": 0,
    "preys": 0,
    "grass": 100,
    "drought": False,
    "droughttick": 0,
}

# -----------------------
# FUNCTIONS
# -----------------------

def encode_msg(s: str) -> bytes:
    return (s + "\n").encode("utf-8")

def decode_msg(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")

def shm_write(shm, lock,
              tick: int, predators: int, preys: int, grass: int, drought: bool) -> None:
    """Mettre à jour la shared memory avec les nouvelles valeurs."""
    with lock:
        shm.buf[:SHM_SIZE] = struct.pack(SHM_FMT, tick, predators, preys, grass, int(drought))

def handle_display_command(mq: sysv_ipc.MessageQueue, cmd: str) -> int:
    """
    Format: "<PID> <ACTION>"
    ACTION: STATUS | QUIT | ADD_PREY | ADD_PREDATOR | ADD_DROUGHT
    Returns:
      0 => stop env
      1 => continue
      2 => spawn prey
      3 => spawn predator
      4 => start drought
    """
    cmd = cmd.strip()
    parts = cmd.split(maxsplit=1)
    if len(parts) != 2:
        print(f"[env] bad display cmd: {cmd!r}")
        return 1

    pid_str, action = parts[0], parts[1].upper()
    try:
        sender_pid = int(pid_str)
    except ValueError:
        print(f"[env] bad sender pid: {pid_str!r}")
        return 1

    if action == "STATUS":
        payload = (
            f"tick={state['tick']} predators={state['predators']} "
            f"preys={state['preys']} grass={state['grass']} drought={state['drought']}"
        )
        mq.send(payload.encode("utf-8"), type=sender_pid)
        return 1

    if action == "QUIT":
        mq.send(b"OK quitting", type=sender_pid)
        return 0

    if action == "ADD_PREY":
        mq.send(b"OK adding prey", type=sender_pid)
        return 2

    if action == "ADD_PREDATOR":
        mq.send(b"OK adding predator", type=sender_pid)
        return 3

    if action == "ADD_DROUGHT":
        print("[env] Drought triggered by display.")
        # Remplaçons os.kill par signal.raise_signal ici
        signal.raise_signal(signal.SIGUSR1)  # Cela envoie le signal à env.py
        mq.send(b"OK drought", type=sender_pid)
        return 4

    mq.send(f"ERR unknown action {action}".encode("utf-8"), type=sender_pid)
    return 1

def handle_drought_signal(signum, frame):
    """ Signal handler qui active la sécheresse. """
    global state  # Utilisation de la variable globale `state`
    print("[env] Drought started!")
    state["drought"] = True
    # Mettre à jour la shared memory avec la nouvelle valeur de drought
    shm_write(shm, lock, state["tick"], state["predators"], state["preys"], state["grass"], state["drought"])

def safe_kill(pid: int, who: str) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"[env] SIGTERM sent to PID {pid} ({who})")
    except ProcessLookupError:
        print(f"[env] PID {pid} already dead ({who})")
    except PermissionError:
        print(f"[env] no permission to kill PID {pid} ({who})")

def parse_line(line: str) -> Tuple[str, str, int]:
    """
    Expected: "<CMD> <KIND> <PID>"
    CMD in {JOIN, FEED, REPRO, DIE}
    KIND in {PREY, PREDATOR}
    """
    parts = line.strip().split()
    if len(parts) != 3:
        raise ValueError(f"bad format (expected 3 tokens): {line!r}")
    cmd = parts[0].upper()
    kind = parts[1].upper()
    pid = int(parts[2])
    if cmd not in {"JOIN", "FEED", "REPRO", "DIE"}:
        raise ValueError(f"unknown cmd: {cmd}")
    if kind not in {"PREY", "PREDATOR"}:
        raise ValueError(f"unknown kind: {kind}")
    return cmd, kind, pid

def run_prey_proc(host: str, port: int, H: int, R: int, e_gain: int, e_decay: int, tick_sleep: float) -> None:
    from prey import agent_main
    agent_main(host, port, H, R, e_gain, e_decay, tick_sleep)

def run_predator_proc(host: str, port: int, H: int, R: int, e_gain: int, e_decay: int, tick_sleep: float) -> None:
    from predator import agent_main
    agent_main(host, port, H, R, e_gain, e_decay, tick_sleep)

def main() -> int:

    global shm, lock  # Rendre shm et lock accessibles dans toute la fonction main

    print(f"[env] PID={os.getpid()} starting")

    mq = sysv_ipc.MessageQueue(MQ_KEY, sysv_ipc.IPC_CREAT)
    print(f"[env] MessageQueue created with key={MQ_KEY} (ipcs -q)")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(50)
    server.setblocking(False)
    print(f"[env] Socket server listening on {HOST}:{PORT}")

    # --- Shared memory init ---
    lock = Lock()

    # cleanup previous shm if crash
    try:
        old = shared_memory.SharedMemory(name=SHM_NAME, create=False)
        old.close()
        old.unlink()
    except FileNotFoundError:
        pass

    shm = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)
    shm_write(shm, lock, state["tick"], state["predators"], state["preys"], state["grass"], state["drought"])

    # --- child processes ---
    children: list[mp.Process] = []

    def spawn_prey(children_list: list[mp.Process]) -> int:
        p = mp.Process(target=run_prey_proc, args=(HOST, PORT, 50, 75, 50, 5, 0.2), daemon=True)
        p.start()
        children_list.append(p)
        return p.pid

    def spawn_predator(children_list: list[mp.Process]) -> int:
        p = mp.Process(target=run_predator_proc, args=(HOST, PORT, 50, 75, 80, 7, 0.2), daemon=True)
        p.start()
        children_list.append(p)
        return p.pid

    # --- agents registry ---
    agents: Dict[int, Dict[str, object]] = {}

    # --- reproduction requires 2 distinct parents ---
    repro_ready: Dict[str, set[int]] = {"PREY": set(), "PREDATOR": set()}

    # --- client sockets ---
    clients = set()
    recv_buf: Dict[socket.socket, str] = {}

    running = 1
    try:
        signal.signal(signal.SIGUSR1, handle_drought_signal)

        while running != 0:
            # ---- simulation tick ----
            state["tick"] += 1

            if state["drought"]:
                state["droughttick"] += 1
            else:
                state["grass"] += 1

            if state["droughttick"] >= DROUGHT_DURATION:
                state["drought"] = False
                state["droughttick"] = 0
                print("[env] End of drought")

            # ---- display MQ ----
            try:
                raw, _t = mq.receive(type=CMD_TYPE, block=False)
                cmd = decode_msg(raw)
                running = handle_display_command(mq, cmd)

                if running == 2:
                    new_pid = spawn_prey(children)
                    print(f"[env] SPAWN PREY -> pid={new_pid}")
                    running = 1
                elif running == 3:
                    new_pid = spawn_predator(children)
                    print(f"[env] SPAWN PREDATOR -> pid={new_pid}")
                    running = 1
                elif running == 4:
                    print("[env] Drought triggered by display.")
                    # Appeler directement la fonction handle_drought_signal() pour gérer la sécheresse
                    handle_drought_signal(signal.SIGUSR1, None)  # envoie le signal à env pour activer la sécheresse
                    running = 1
            except sysv_ipc.BusyError:
                pass

            # ---- socket multiplexing ----
            rlist = [server] + list(clients)
            readable, _, exceptional = select.select(rlist, [], rlist, 0)

            # accept new connections
            if server in readable:
                while True:
                    try:
                        cs, addr = server.accept()
                        cs.setblocking(False)
                        clients.add(cs)
                        recv_buf[cs] = ""
                        if DEBUG:
                            print(f"[env] accepted connection from {addr}")
                    except BlockingIOError:
                        break

            # handle client data
            for cs in list(clients):
                if cs not in readable:
                    continue
                try:
                    data = cs.recv(4096)
                except (BlockingIOError, InterruptedError):
                    continue
                except ConnectionResetError:
                    # client killed/crashed
                    clients.remove(cs)
                    recv_buf.pop(cs, None)
                    try:
                        cs.close()
                    except Exception:
                        pass
                    continue

                if not data:
                    clients.remove(cs)
                    recv_buf.pop(cs, None)
                    try:
                        cs.close()
                    except Exception:
                        pass
                    continue

                recv_buf[cs] += decode_msg(data)

                while "\n" in recv_buf[cs]:
                    line, rest = recv_buf[cs].split("\n", 1)
                    recv_buf[cs] = rest
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        cmd, kind, pid = parse_line(line)
                    except Exception as e:
                        cs.sendall(encode_msg(f"ERR {e}"))
                        continue

                    if cmd == "JOIN":
                        agents[pid] = {"kind": kind, "alive": True}
                        if kind == "PREY":
                            state["preys"] += 1
                        else:
                            state["predators"] += 1
                        cs.sendall(encode_msg("OK JOIN"))
                        print(f"[env] {kind} joined pid={pid}")
                        continue

                    if cmd == "REPRO":
                        repro_ready[kind].add(pid)
                        if len(repro_ready[kind]) >= 2:
                            parent1 = repro_ready[kind].pop()
                            parent2 = repro_ready[kind].pop()
                            # Appliquer le taux de réussite de reproduction
                            success_rate = PREY_REPRO_SUCCESS_RATE if kind == "PREY" else PREDATOR_REPRO_SUCCESS_RATE
                            if random.random() < success_rate:
                                if kind == "PREY":
                                    new_pid = spawn_prey(children)
                                    print(f"[env] BIRTH PREY: parents=({parent1},{parent2}) -> pid={new_pid}")
                                else:
                                    new_pid = spawn_predator(children)
                                    print(f"[env] BIRTH PREDATOR: parents=({parent1},{parent2}) -> pid={new_pid}")
                                cs.sendall(encode_msg("OK REPRO BIRTH"))
                            else:
                                print(f"[env] REPRO FAILED {kind}: parents=({parent1},{parent2})")
                                cs.sendall(encode_msg("OK REPRO FAILED"))
                        else:
                            cs.sendall(encode_msg("OK REPRO WAITING"))
                        continue

                    if cmd == "FEED":
                        if kind == "PREY":
                            if state["grass"] >= G :
                                state["grass"] -= G
                                cs.sendall(encode_msg("OK FEED GRASS"))
                                if DEBUG:
                                    print(f"[env] prey pid={pid} ate grass (-{G})")
                            else:
                                cs.sendall(encode_msg("NO NO_GRASS"))
                            continue

                        # predator eats prey if any
                        if state["preys"] > 0:
                            state["preys"] -= 1
                            prey_pid_to_kill = None
                            for apid, info in agents.items():
                                if info.get("alive") and info.get("kind") == "PREY":
                                    prey_pid_to_kill = apid
                                    break
                            if prey_pid_to_kill is not None:
                                agents[prey_pid_to_kill]["alive"] = False
                                repro_ready["PREY"].discard(prey_pid_to_kill)
                                safe_kill(prey_pid_to_kill, "prey eaten")
                            cs.sendall(encode_msg("OK FEED PREY"))
                            print(f"[env] predator pid={pid} ate a prey")
                        else:
                            cs.sendall(encode_msg("NO NO_PREY"))
                        continue

                    if cmd == "DIE":
                        info = agents.get(pid)
                        if info and info.get("alive"):
                            info["alive"] = False
                            if kind == "PREY":
                                state["preys"] = max(0, state["preys"] - 1)
                            else:
                                state["predators"] = max(0, state["predators"] - 1)

                        repro_ready["PREY"].discard(pid)
                        repro_ready["PREDATOR"].discard(pid)

                        cs.sendall(encode_msg("OK DIE"))
                        print(f"[env] {kind} pid={pid} died (requested)")
                        safe_kill(pid, f"{kind.lower()} died")
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

            # ---- update shared memory EVERY TICK ----
            shm_write(
                shm, lock,
                tick=state["tick"],
                predators=state["predators"],
                preys=state["preys"],
                grass=state["grass"],
                drought=state["drought"],
            )

            time.sleep(TICK_SLEEP)

    except KeyboardInterrupt:
        print("\n[env] KeyboardInterrupt -> exiting")

    finally:
        # close clients
        for cs in list(clients):
            try:
                cs.close()
            except Exception:
                pass
        clients.clear()

        try:
            server.close()
        except Exception:
            pass

        try:
            mq.remove()
            print("[env] MessageQueue removed")
        except Exception as e:
            print(f"[env] Warning: failed to remove queue: {e}", file=sys.stderr)

        for p in children:
            if p.is_alive():
                p.terminate()
        for p in children:
            p.join(timeout=1)

        try:
            shm.close()
            shm.unlink()
        except Exception:
            pass

    print("[env] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
