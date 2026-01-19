#!/usr/bin/env python3
import sysv_ipc
import struct

SHM_KEY = 222
SEM_KEY = 333

STRUCT_FMT = "iiii"  # grass, preys, predators, drought
SIZE = struct.calcsize(STRUCT_FMT)


def attach_shared(create=False):
    shm = sysv_ipc.SharedMemory(
        SHM_KEY,
        sysv_ipc.IPC_CREAT if create else 0,
        size=SIZE
    )
    sem = sysv_ipc.Semaphore(
        SEM_KEY,
        sysv_ipc.IPC_CREAT if create else 0,
        initial_value=1
    )
    return shm, sem


def read_state(shm, sem):
    sem.acquire()
    data = shm.read()
    sem.release()
    return struct.unpack(STRUCT_FMT, data)


def write_state(shm, sem, grass, preys, predators, drought):
    sem.acquire()
    shm.write(struct.pack(STRUCT_FMT, grass, preys, predators, drought))
    sem.release()
