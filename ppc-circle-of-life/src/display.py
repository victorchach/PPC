#!/usr/bin/env python3
import os
import sys
import sysv_ipc

MQ_KEY = 111
CMD_TYPE = 1


def encode_msg(s):
    return s.encode()


def decode_msg(b):
    return b.decode(errors="replace")


def send_cmd(mq, pid, action):
    mq.send(encode_msg(f"{pid} {action}"), type=CMD_TYPE)
    resp, _ = mq.receive(type=pid)
    return decode_msg(resp)


def main():
    pid = os.getpid()
    mq = sysv_ipc.MessageQueue(MQ_KEY)

    while True:
        print("\n1) status\n2) drought\n3) quit env\n4) exit")
        c = input("> ").strip()

        if c == "1":
            print(send_cmd(mq, pid, "STATUS"))
        elif c == "2":
            print(send_cmd(mq, pid, "ADD_DROUGHT"))
        elif c == "3":
            print(send_cmd(mq, pid, "QUIT"))
        elif c == "4":
            break


if __name__ == "__main__":
    main()
