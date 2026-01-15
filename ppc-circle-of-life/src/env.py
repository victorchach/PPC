#!/usr/bin/env python3
import os
import sys
import time
import socket
import select
import signal
from typing import Dict, Tuple
import multiprocessing as mp
from pathlib import Path


import sysv_ipc  # imposée par le cours/projet (System V MQ)

# -----------------------
# CONFIG
# -----------------------
MQ_KEY = 111
CMD_TYPE = 1

HOST = "127.0.0.1"
PORT = 1789

G = 10                 # herbe consommée par un prey quand il FEED
TICK_SLEEP = 0.2       # pas de simulation

DEBUG = True


def encode_msg(s: str) -> bytes:
    return (s + "\n").encode("utf-8")


def decode_msg(b: bytes) -> str:
    return b.decode("utf-8", errors="replace")


def handle_display_command(mq: sysv_ipc.MessageQueue, state: dict, cmd: str) -> int:
    """
    Format: "<PID> <ACTION>"
    ACTION: STATUS | QUIT | ADD_PREY | ADD_PREDATOR
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
    
    mq.send(f"ERR unknown action {action}".encode("utf-8"), type=sender_pid)
    return True


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
    print(f"[env] PID={os.getpid()} starting")

    # --- MQ ---
    mq = sysv_ipc.MessageQueue(MQ_KEY, sysv_ipc.IPC_CREAT)
    print(f"[env] MessageQueue created with key={MQ_KEY} (ipcs -q)")

    # --- Non-blocking TCP server ---
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(50)
    server.setblocking(False)
    print(f"[env] Socket server listening on {HOST}:{PORT}")

    # --- State ---
    state = {
        "tick": 0,
        "predators": 0,
        "preys": 0,
        "grass": 100,
        "drought": False,
    }
    # --- processus enfants de env ---
    children: list[mp.Process] = []
    
    def spawn_prey(children: list[mp.Process]) -> int:
        p = mp.Process(target=run_prey_proc, args=(HOST, PORT, 50, 75, 50, 5, 0.2), daemon=True)
        p.start()
        children.append(p)
        return p.pid

    def spawn_predator(children: list[mp.Process]) -> int:
        p = mp.Process(target=run_predator_proc, args=(HOST, PORT, 50, 75, 80, 7, 0.2), daemon=True)
        p.start()
        children.append(p)
        return p.pid



    # --- Agents registry ---
    # agents[pid] = {"kind": "PREY"/"PREDATOR", "alive": True}
    agents: Dict[int, Dict[str, object]] = {}

    # --- Reproduction sexuée: 2 parents distincts requis ---
    repro_ready: Dict[str, set[int]] = {
        "PREY": set(),
        "PREDATOR": set(),
    }


    # --- Client sockets ---
    clients = set()                 # set[socket.socket]
    recv_buf: Dict[socket.socket, str] = {}  # per-client text buffer

    running = 1
    try:
        while running != 0 :
            # ---- simulation tick ----
            state["tick"] += 1
            if not state["drought"]:
                state["grass"] += 1

            # ---- display MQ (non-blocking) ----
            try:
                raw, _t = mq.receive(type=CMD_TYPE, block=False)
                cmd = decode_msg(raw)
                running = handle_display_command(mq, state, cmd)
                if running == 2 : 
                    new_pid = spawn_prey(children)
                    print(f"[env] BIRTH PREY -> spawned pid={new_pid}")
                if running == 3 :
                    new_pid = spawn_predator(children)
                    print(f"[env] BIRTH PREDATOR -> spawned pid={new_pid}")
            except sysv_ipc.BusyError:
                pass

            # ---- socket multiplexing ----
            rlist = [server] + list(clients)
            readable, _, exceptional = select.select(rlist, [], rlist, 0)

            # handle new connections
            if server in readable:
                while True:
                    try:
                        cs, addr = server.accept()
                        cs.setblocking(False)
                        clients.add(cs)
                        recv_buf[cs] = ""
                        if DEBUG:
                            print(f"[env] accepted connection from {addr}")
                    except BlockingIOError: #a built-in exception that occurs when an input/output (I/O) operation is blocked. This exception is typically raised when a non-blocking operation is requested, but it can't be completed immediately.
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
                    # le client a été tué / a crash -> on ferme proprement
                    clients.remove(cs)
                    recv_buf.pop(cs, None)
                    try:
                        cs.close()
                    except Exception:
                        pass
                    continue


                if not data:
                    # client closed
                    clients.remove(cs)
                    recv_buf.pop(cs, None)
                    try:
                        cs.close()
                    except Exception:
                        pass
                    continue

                recv_buf[cs] += decode_msg(data)

                # process full lines
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

                    # ---- COMMANDS ----
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
                        # 1) on enregistre ce PID comme "prêt à se reproduire"
                        repro_ready[kind].add(pid)

                        # 2) si on a au moins 2 parents distincts, on fait un birth
                        if len(repro_ready[kind]) >= 2:
                            # on prend 2 parents distincts et on les enlève du set
                            parent1 = repro_ready[kind].pop()
                            parent2 = repro_ready[kind].pop()
                            # spawn réel + update state
                            if kind == "PREY":
                                new_pid = spawn_prey(children)
                                print(f"[env] BIRTH PREY: parents=({parent1},{parent2}) -> spawned pid={new_pid}")
                            else:
                                new_pid = spawn_predator(children)
                                print(f"[env] BIRTH PREDATOR: parents=({parent1},{parent2}) -> spawned pid={new_pid}")
                            cs.sendall(encode_msg("OK REPRO BIRTH"))
                        else:
                            cs.sendall(encode_msg("OK REPRO WAITING"))
                        continue

                    if cmd == "FEED":
                        if kind == "PREY":
                            if state["grass"] >= G:
                                state["grass"] -= G
                                cs.sendall(encode_msg("OK FEED GRASS"))
                                if DEBUG:
                                    print(f"[env] prey pid={pid} ate grass (-{G})")
                            else:
                                cs.sendall(encode_msg("NO NO_GRASS"))
                            continue

                        # PREDATOR feeding: eat 1 prey if any
                        if state["preys"] > 0:
                            state["preys"] -= 1

                            # Try to kill one known alive prey process
                            prey_pid_to_kill = None
                            for apid, info in agents.items():
                                if info.get("alive") and info.get("kind") == "PREY":
                                    prey_pid_to_kill = apid
                                    break
                            if prey_pid_to_kill is not None:
                                agents[prey_pid_to_kill]["alive"] = False
                                safe_kill(prey_pid_to_kill, "prey eaten")
                                repro_ready["PREY"].discard(prey_pid_to_kill)
                            cs.sendall(encode_msg("OK FEED PREY"))
                            print(f"[env] predator pid={pid} ate a prey")
                        else:
                            cs.sendall(encode_msg("NO NO_PREY"))
                        continue

                    if cmd == "DIE":
                        # mark dead + decrement counts
                        info = agents.get(pid)
                        if info and info.get("alive"):
                            info["alive"] = False
                            if kind == "PREY":
                                state["preys"] = max(0, state["preys"] - 1)
                            else:
                                state["predators"] = max(0, state["predators"] - 1)
                        # retirer ce pid des "candidats reproduction" (si présent)
                        repro_ready["PREY"].discard(pid)
                        repro_ready["PREDATOR"].discard(pid)

                        cs.sendall(encode_msg("OK DIE"))
                        print(f"[env] {kind} pid={pid} died (requested)")
                        safe_kill(pid, f"{kind.lower()} died")
                        continue

            # handle exceptional sockets
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

    print("[env] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
