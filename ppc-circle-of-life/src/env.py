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
import threading

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

# Manager().list() pour gérer les pid des Preys (dynamique)
manager = None
prey_pid_list = None
repro_ready_prey = None
repro_ready_predator = None
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

# Drought internal counter (env only)
drought_tick = 0

# Globals set in main
shm = None
sem = None

stop_event = threading.Event()  # Event to stop all threads

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

def run_prey_proc(host, port, prey_pid_list, repro_ready_predator, repro_ready_prey):
    from prey import agent_main
    agent_main(host, port, prey_pid_list, repro_ready_predator, repro_ready_prey)

def run_predator_proc(host, port, prey_pid_list, repro_ready_predator, repro_ready_prey):
    from predator import agent_main
    agent_main(host, port, prey_pid_list, repro_ready_predator, repro_ready_prey)

def spawn_prey(children):
    p = mp.Process(target=run_prey_proc, args=(HOST, PORT, prey_pid_list, repro_ready_predator, repro_ready_prey), daemon=False)
    p.start()
    children.append(p)
    prey_pid_list.append(p.pid)  # Ajouter le PID de la proie dans la manager.list
    return p.pid

def spawn_predator(children):
    p = mp.Process(target=run_predator_proc, args=(HOST, PORT, prey_pid_list, repro_ready_predator, repro_ready_prey), daemon=False)
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

#-----------------------------
#   DEFINITION DES THREADS
#-----------------------------

def thread_simulation(shm, sem, drought_tick):
    while not stop_event.is_set():
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
            time.sleep(TICK_SLEEP)


def thread_socket(server, clients, recv_buf):
    while not stop_event.is_set():
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


def thread_display(mq, children, stop_event):
    while not stop_event.is_set():
        # ---- display MQ ----
            try:
                raw, _t = mq.receive(type=CMD_TYPE, block=False)
                cmd = decode_bytes(raw)
                keep = handle_display_command(mq, children, cmd)
                if keep == 0:
                    stop_event.set()
            except sysv_ipc.BusyError:
                pass



def main():
    global shm, sem, drought_tick,manager, prey_pid_list, repro_ready_predator, repro_ready_prey

    print(f"[env] PID={os.getpid()} starting")

    # MQ
    mq = sysv_ipc.MessageQueue(MQ_KEY, sysv_ipc.IPC_CREAT)
    print(f"[env] MessageQueue created key={MQ_KEY}")

    # Semaphore (SysV) for SHM
    sem = sysv_ipc.Semaphore(SEM_KEY, sysv_ipc.IPC_CREAT, initial_value=1)
    print(f"[env] Semaphore created key={SEM_KEY}")

    # Shared memory & pid_prey_queue init 
    try:
        old = shared_memory.SharedMemory(name=SHM_NAME, create=False)
        old.close()
        old.unlink()
    except FileNotFoundError:
        pass

    shm = shared_memory.SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)
    
    manager = mp.Manager()
    prey_pid_list = manager.list()
    repro_ready_prey = manager.list()
    repro_ready_predator = manager.list()

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

    # Start threads
    t_sim = threading.Thread(target=thread_simulation, args=(shm, sem, drought_tick), daemon=False)
    t_sock = threading.Thread(target=thread_socket, args=(server, clients, recv_buf), daemon=False)
    t_disp = threading.Thread(target=thread_display, args=(mq, children, stop_event), daemon=False)

    t_sim.start()
    t_sock.start()
    t_disp.start()

    # Keep the main process alive
    try:
        while not stop_event.is_set():
            time.sleep(1)
        
        t_sim.join(timeout=1)
        t_sock.join(timeout=1)
        t_disp.join(timeout=1)

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
