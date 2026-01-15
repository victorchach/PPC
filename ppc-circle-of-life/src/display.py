#!/usr/bin/env python3
import os
import sys

# ⚠️ LIBRAIRIE NON-STANDARD (imposée par le sujet)
import sysv_ipc

MQ_KEY = 111
CMD_TYPE = 1


def encode_msg(s: str) -> bytes:
    return s.encode("utf-8") #on encode str s avec utf-8


def decode_msg(b: bytes) -> str:
    return b.decode("utf-8", errors="replace") #on decode bytes b supposé codé en utf-8 et on remplace les erreurs par symbole "replace"


def send_cmd(mq: sysv_ipc.MessageQueue, my_pid: int, action: str) -> str:
    """
    Envoie une commande à env via type=1, puis attend la réponse via type=my_pid.
    """
    cmd = f"{my_pid} {action}"
    mq.send(encode_msg(cmd), type=CMD_TYPE) #on envoie au mq partagé avec env un message de la forme (message_bytes, message_type)
    resp_bytes, _t = mq.receive(type=my_pid)  # bloquant: on attend la réponse de la forme : (message_bytes, message_type) on garde message_byte dans resp_bytes, on s'en fout du type donc _t
    return decode_msg(resp_bytes)


def main() -> int:
    my_pid = os.getpid()
    print(f"[display] PID={my_pid}")

    try:
        mq = sysv_ipc.MessageQueue(MQ_KEY)  # connexion (la queue doit exister)
    except sysv_ipc.ExistentialError:
        print("[display] Cannot connect to message queue. Start env.py first.", file=sys.stderr)
        return 1

    while True:
        print("\n--- DISPLAY ---")
        print("1) status")
        print("2) add prey")
        print("3) add predator")
        print("4) quit env")
        print("5) exit display")
        choice = input("> ").strip()

        if choice == "1":
            resp = send_cmd(mq, my_pid, "STATUS")
            print("[display] env:", resp)

        elif choice == "2":
            resp = send_cmd(mq, my_pid, "ADD_PREY")
            print("[display] env:", resp)

        elif choice == "3":
            resp = send_cmd(mq, my_pid, "ADD_PREDATOR")
            print("[display] env:", resp)
        
        elif choice == "4":
            resp = send_cmd(mq, my_pid, "QUIT")
            print("[display] env:", resp)
        
        elif choice == "5":
            print("[display] bye")
            return 0

        else:
            print("[display] unknown choice")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
