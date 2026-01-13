#!/usr/bin/env python3
import socket
import time
import os

HOST = "127.0.0.1" # je cherche/j'envoie en local
PORT = 1789 #je cherche/j'envoie en plus sur le port 1789 
            #(normal car on a choisi arbitrairement c'est la que env.py attend des infos donc on va pas envoyer ailleurs)

def main() -> int:
    print(f"[predator] PID={os.getpid()} joining...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s: #on ouvre une nouvelle socket en IPv4, TCP
        s.connect((HOST, PORT)) #on se connecte
        s.sendall(b"JOIN PREDATOR") # on envoie a tlm sur la socket
        resp = s.recv(1024) #on att une reponse de 1024b
        print("[predator] env response:", resp.decode("utf-8", errors="replace").strip()) #on traduit la réponse et on la clean

    # On reste vivant un peu (pour debug / futur comportement agent)
    time.sleep(2)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())            #pour eviter que ça se lance avec les import.
