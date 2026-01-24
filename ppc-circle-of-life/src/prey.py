#!/usr/bin/env python3
# prey.py
import os
import time
import socket
import random
import struct
import signal
from multiprocessing import shared_memory
import multiprocessing as mp
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

def run_prey_proc(host, port, prey_pid_queue, repro_ready_predator, repro_ready_prey):
    agent_main(host, port, prey_pid_queue, repro_ready_predator, repro_ready_prey)

def spawn_prey(children, prey_pid_queue, repro_ready_predator, repro_ready_prey):
    p = mp.Process(target=run_prey_proc, args=(HOST, PORT, prey_pid_queue, repro_ready_predator, repro_ready_prey), daemon=False)
    p.start()
    children.append(p)
    prey_pid_queue.put(p.pid)  # Ajouter le PID de la proie dans la Queue
    return p.pid

def removeQUEUE(queue, valeur): # on prend une queue et une valeur, on renvoie une queue avec cette valeur supprimée
    """Supprime un élément de la Queue."""
    temp_list = []
    
    while not queue.empty():
        temp_list.append(queue.get())

    temp_list = [i for i in temp_list if i != valeur]

    for i in temp_list:
        queue.put(i)

def longueurQUEUE(queue):
    temp_list = []
    queue_cpy = queue
    if not queue_cpy.empty() :
        while not queue_cpy.empty():
            temp_list.append(queue_cpy.get())
        return len(temp_list)
    else:
        return 0

def value_inQUEUE(queue, valeur): # renvoie true si valeur est dans queue, False sinon
    temp_list = []
    cpy_queue = queue
    while not cpy_queue.empty():
        temp_list.append(cpy_queue.get())
    for i in temp_list :
        if i == valeur :
            return True
    return False

def agent_main(host, port, prey_pid_queue, repro_ready_predator, repro_ready_prey):
    pid = os.getpid()
    print(f"[prey] PID={pid} starting")
    children = []
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
            energy -= E_DECAY

            if energy <= 0:
                # die => decrement preys in SHM
                sem.acquire()
                try:
                    tick, predators, preys, grass, drought = unpack(shm.buf)
                    preys = max(0, preys - 1)
                    shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
                finally:
                    sem.release()
                print(f"[prey] died energy={energy}")
                removeQUEUE(prey_pid_queue, os.getpid())  # on s'enlève de la queue des pid
                removeQUEUE(repro_ready_prey, os.getpid())
                os.kill(os.getpid(), signal.SIGTERM)  # Terminates the process
                
                break

            # FEED directly from SHM
            if energy < H:
                sem.acquire()
                try:
                    tick, predators, preys, grass, drought = unpack(shm.buf)
                    if grass >= G:
                        grass = grass - G
                        shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
                        energy += E_GAIN
                        # debug
                        print(f"[prey] ate grass (-{G})")
                finally:
                    sem.release()

            # REPRO via socket (env spawns; SHM population increment happens in child on JOIN)
            if energy > R:
                if value_inQUEUE(repro_ready_predator, os.getpid()) == False :
                    repro_ready_prey.put(os.getpid())

                if longueurQUEUE(repro_ready_prey) >= 2:
                    p1 = repro_ready_prey.get()
                    p2 = repro_ready_prey.get()
                    new_pid = spawn_prey(children, prey_pid_queue, repro_ready_predator, repro_ready_prey)
                    print(f"[prey] birth PREY pid={new_pid} parents=({p1},{p2})")
    
                else:
                    print("[prey] OK PREY REPRO WAITING")
                
                energy -= 25
                continue
            time.sleep(TICK_SLEEP)

    shm.close()

def main():
    agent_main(HOST, PORT, None)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
