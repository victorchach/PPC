#!/usr/bin/env python3
# display.py
import os
import sysv_ipc

MQ_KEY = 111
CMD_TYPE = 1

def send_cmd(mq, my_pid, action):
    msg = f"{my_pid} {action}\n".encode("utf-8")
    mq.send(msg, type=CMD_TYPE)
    resp_bytes, _t = mq.receive(type=my_pid)  # blocking
    return resp_bytes.decode("utf-8", errors="replace")

def main():
    my_pid = os.getpid()
    print(f"[display] PID={my_pid}")

    mq = sysv_ipc.MessageQueue(MQ_KEY)  # env must be started first

    while True:
        print("\n--- DISPLAY ---")
        print("1) status")
        print("2) add prey")
        print("3) add predator")
        print("4) add drought")
        print("5) quit env")
        print("6) exit display")
        choice = input("> ").strip()

        if choice == "1":
            print("[display] env:", send_cmd(mq, my_pid, "STATUS"))

        elif choice == "2":
            print("[display] env:", send_cmd(mq, my_pid, "ADD_PREY"))

        elif choice == "3":
            print("[display] env:", send_cmd(mq, my_pid, "ADD_PREDATOR"))

        elif choice == "4":
            print("[display] env:", send_cmd(mq, my_pid, "ADD_DROUGHT"))

        elif choice == "5":
            print("[display] env:", send_cmd(mq, my_pid, "QUIT"))
            break

        elif choice == "6":
            break

        else:
            print("Invalid choice")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())