#!/usr/bin/env python3
import os
import sys
import time
import socket
import select

# ⚠️ Librairie NON standard (mais imposée par le cours/projet pour System V MQ)
import sysv_ipc

# -----------------------
# CONFIG MINIMALE
# -----------------------
MQ_KEY = 111          # Clé System V (int). Doit matcher display.py
CMD_TYPE = 1          # Type des messages envoyés à env (commandes display->env)

HOST = "127.0.0.1"
PORT = 1789           # Port TCP pour JOIN predator/prey
G=10


def encode_msg(s: str) -> bytes:
    """System V message queues échangent des bytes."""
    return s.encode("utf-8")


def decode_msg(b: bytes) -> str:
    """Convertit bytes -> str."""
    return b.decode("utf-8", errors="replace")


def handle_display_command(mq: sysv_ipc.MessageQueue, state: dict, cmd: str) -> bool:
    """
    Traite une commande venant du display.
    Format attendu: "<PID> <ACTION>"
    Ex: "12345 STATUS" ou "12345 QUIT"

    Retourne True si on doit continuer, False si on doit arrêter env.
    """
    cmd = cmd.strip()
    parts = cmd.split(maxsplit=1)
    if len(parts) != 2:
        print(f"[env] bad command format: {cmd!r}")
        return True

    sender_pid_str, action = parts[0], parts[1].upper()
    try:
        sender_pid = int(sender_pid_str)
    except ValueError:
        print(f"[env] bad sender pid: {sender_pid_str!r}")
        return True

    if action == "STATUS":
        payload = (
            f"tick={state['tick']} predators={state['predators']} "
            f"preys={state['preys']} grass={state['grass']} drought={state['drought']}"
        )
        mq.send(encode_msg(payload), type=sender_pid)
        return True

    if action == "QUIT":
        mq.send(encode_msg("OK quitting"), type=sender_pid)
        return False

    mq.send(encode_msg(f"ERR unknown action {action}"), type=sender_pid)
    return True


def handle_join(server_socket: socket.socket, state: dict) -> None:
    """
    Accepte (si disponible) une connexion JOIN non-bloquante.
    Le client envoie:
      - "JOIN PREDATOR"
      - "JOIN PREY"
    """
    readable, _, _ = select.select([server_socket], [], [], 0)
    if server_socket not in readable:
        return

    client_socket, address = server_socket.accept()
    with client_socket:
        data = client_socket.recv(1024)
        msg = data.decode("utf-8", errors="replace").strip()

        if msg == "JOIN PREDATOR":
            state["predators"] += 1
            client_socket.sendall(b"OK\n")
            print(f"[env] predator joined from {address}")

        elif msg == "JOIN PREY":
            state["preys"] += 1
            client_socket.sendall(b"OK\n")
            print(f"[env] prey joined from {address}")
        
        else:
            client_socket.sendall(b"ERR\n")
            print(f"[env] bad join msg from {address}: {msg!r}")


def main() -> int:
    print(f"[env] PID={os.getpid()} starting")

    # 1) Message Queue
    mq = sysv_ipc.MessageQueue(MQ_KEY, sysv_ipc.IPC_CREAT)
    print(f"[env] MessageQueue created with key={MQ_KEY} (check with: ipcs -q)")

    # 2) Socket server (non-bloquant)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen(10)
    server_socket.setblocking(False)
    print(f"[env] Socket server listening on {HOST}:{PORT}")

    # 3) Etat minimal (V1/V2)
    state = {
        "tick": 0,
        "predators": 0,
        "preys": 0,
        "grass": 100,
        "drought": False,
    }

    running = True
    try:
        while running:
            # ---- Simulation minimale (pour voir des valeurs bouger) ----
            state["tick"] += 1
            if not state["drought"]:
                state["grass"] += 1

            # ---- 1) Lire commandes display via MQ (non-bloquant) ----
            try:
                raw, _msg_type = mq.receive(type=CMD_TYPE, block=False)
                cmd = decode_msg(raw)
                running = handle_display_command(mq, state, cmd)
            except sysv_ipc.BusyError:
                pass  # aucune commande

            # ---- 2) Accepter des JOIN via socket (non-bloquant) ----
            handle_join(server_socket, state)

            # ---- 3) Pause pour éviter CPU à 100% ----
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\n[env] KeyboardInterrupt -> exiting")

    finally:
        # Nettoyage socket
        try:
            server_socket.close()
        except Exception:
            pass

        # Nettoyage MQ (important)
        try:
            mq.remove()
            print("[env] MessageQueue removed")
        except Exception as e:
            print(f"[env] Warning: failed to remove queue: {e}", file=sys.stderr)

    print("[env] stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
