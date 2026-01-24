#!/usr/bin/env python3
# predator.py
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

def run_predator_proc(host, port, prey_pid_list, repro_ready_predator, repro_ready_prey):
    agent_main(host, port, prey_pid_list, repro_ready_predator, repro_ready_prey)

def spawn_predator(children, prey_pid_list, repro_ready_predator, repro_ready_prey):
    p = mp.Process(target=run_predator_proc, args=(HOST, PORT, prey_pid_list, repro_ready_predator, repro_ready_prey), daemon=False)
    p.start()
    children.append(p)
    return p.pid

def removeLIST(lst, valeur): #Supprime 'valeur' de la liste partagée si présent.
    try:
        while True:
            lst.remove(valeur)
    except ValueError:
        pass

def longueurLIST(lst):
    return len(lst)

def random_valueLIST(lst): #renvoie un valeure random de la manager.liste() list
    snap = list(lst)
    if len(snap) == 0:
        return None
    return random.choice(snap)

def value_inLIST(lst, valeur): #renvoi true si valeur est dans lst, false sinon 
    return valeur in list(lst)

def agent_main(host, port, prey_pid_list, repro_ready_predator, repro_ready_prey):
    pid = os.getpid()
    print(f"[predator] PID={pid} starting")
    children = []
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

        energy = 100

        while True:
            energy -= E_DECAY

            if energy <= 0:
                # die => decrement predators
                sem.acquire()
                try:
                    tick, predators, preys, grass, drought = unpack(shm.buf)
                    predators = max(0, predators - 1)
                    shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
                finally:
                    sem.release()
                print(f"[predator] died energy={energy}")
                removeLIST(repro_ready_predator, os.getpid())
                os.kill(os.getpid(), signal.SIGTERM)  # Terminates the process
                break

            # FEED directly: eat one prey if available
            if energy < H:
                ate = False
                sem.acquire()
                try:
                    tick, predators, preys, grass, drought = unpack(shm.buf)
                    if preys > 0 :
                        # Choisir une proie au hasard
                        prey_pid = random_valueLIST(prey_pid_list)  # prendre un PID au hasard
                        
                        if prey_pid is not None:
                            os.kill(prey_pid, signal.SIGTERM)
                            removeLIST(prey_pid_list, prey_pid)
                            removeLIST(repro_ready_prey, prey_pid)
                            preys = max(0, preys - 1)
                            shm.buf[:SHM_SIZE] = pack(tick, predators, preys, grass, drought)
                            ate = True
                finally:
                    sem.release()

                if ate:
                    energy += E_GAIN
                    # print("[predator] ate a prey")

            # REPRO
            if energy > R:
                if value_inLIST(repro_ready_predator, os.getpid()) == False : 
                    repro_ready_predator.append(os.getpid())
                
                if longueurLIST(repro_ready_predator) >= 2:
                    p1 = repro_ready_predator.pop(0)
                    p2 = repro_ready_predator.pop(0)
                    new_pid = spawn_predator(children, prey_pid_list, repro_ready_predator, repro_ready_prey)
                    print(f"[prey] birth PREDATOR pid={new_pid} parents=({p1},{p2})")
    
                else:
                    print("OK PREDATOR REPRO WAITING")
                energy -= 15

            time.sleep(TICK_SLEEP)

    shm.close()

def main():
    agent_main(HOST, PORT, None)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
