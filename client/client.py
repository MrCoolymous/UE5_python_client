#!/usr/bin/env python3
from __future__ import annotations
import sys
sys.dont_write_bytecode = True

import argparse
import socket
import time
import traceback
from datetime import datetime

from app_config import LOCAL_NETWORK_VERSION
from net.handlers.stateless_connect import StatelessConnectHandlerComponent
from net.connection import NetConnection
from net.packets.control import NMT
from net.state.session_state import get_session_state
from constants import SEQ_NUMBER_MASK

class Logger:
    __slots__ = ('terminal', 'log')

    def __init__(self, filename: str):
        self.terminal = sys.stdout
        self.log = open(filename, "w", encoding="utf-8")

    def write(self, message: str) -> None:
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self) -> None:
        self.terminal.flush()
        self.log.flush()


_logger: Logger | None = None


def configure_output_logging() -> None:
    global _logger
    if _logger is not None:
        return

    log_file = f"client_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    _logger = Logger(log_file)
    sys.stdout = _logger
    sys.stderr = _logger

# Configuration
DEFAULT_SERVER_IP = "127.0.0.1"
DEFAULT_SERVER_PORT = 7777
TIMEOUT = 1.0
KEEPALIVE_INTERVAL = 10.0


def main(server_ip: str, server_port: int):
    print("=" * 60)
    print(f"Server: {server_ip}:{server_port}")
    print("=" * 60)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(TIMEOUT)

    display_name = "Player"

    stateless = StatelessConnectHandlerComponent(
        CachedClientID=0,
        LocalNetworkVersion=LOCAL_NETWORK_VERSION
    )

    try:
        # Step 1: Initial handshake
        pkt = stateless.get_initial_packet()
        print(f"[->] Init               ({len(pkt)}) {pkt.hex()}")
        sock.sendto(pkt, (server_ip, server_port))
        print(f"[INFO] Client local port: {sock.getsockname()[1]}")

        # Step 2: Receive challenge
        data, addr = sock.recvfrom(4096)
        print(f"[<-] Challenge          ({len(data)}) {data.hex()}")
        challenge = stateless.parse_handshake_packet(data)

        if challenge.LocalNetworkVersion != 0:
            print(f"[INFO] Server NetworkVersion: {challenge.LocalNetworkVersion}")
            if challenge.LocalNetworkVersion != LOCAL_NETWORK_VERSION:
                print(f"[WARN] Version mismatch! Client: {LOCAL_NETWORK_VERSION}")
            stateless.LocalNetworkVersion = challenge.LocalNetworkVersion

        # Step 3: Challenge response
        pkt = stateless.get_challenge_response_packet(challenge)
        print(f"[->] Challenge Response ({len(pkt)}) {pkt.hex()}")
        sock.sendto(pkt, (server_ip, server_port))

        # Step 4: Challenge ack
        data, addr = sock.recvfrom(4096)
        print(f"[<-] Challenge Ack      ({len(data)}) {data.hex()}")
        ack = stateless.parse_handshake_packet(data)

        stateless.CachedClientID = ack.CachedClientID
        print(f"[INFO] CachedClientID: {ack.CachedClientID}")

        in_seq = int.from_bytes(ack.Cookie[0:2], "little") & SEQ_NUMBER_MASK
        out_seq = int.from_bytes(ack.Cookie[2:4], "little") & SEQ_NUMBER_MASK
        print(f"[INFO] InSeq: {in_seq}, OutSeq: {out_seq}")

        net_version = challenge.LocalNetworkVersion or LOCAL_NETWORK_VERSION
        conn = NetConnection(
            cached_client_id=ack.CachedClientID,
            initial_in_seq=in_seq,
            initial_out_seq=out_seq,
            local_network_version=net_version,
        )
        session_state = get_session_state(conn)

        conn.set_handlers([stateless])

        # Step 5: Hello
        pkt = NMT.Hello.Get(conn)
        print(f"[->] NMT_Hello          ({len(pkt)}) {pkt.hex()}")
        sock.sendto(pkt, (server_ip, server_port))

        session_state.login_params = {
            "URL": f"?Name={display_name}",
        }

        print("\n" + "=" * 60)
        print("Connected! Listening...")
        print("=" * 60 + "\n")

        last_send = time.time()

        while True:
            try:
                data, addr = sock.recvfrom(4096)
                print(f"[<-] Server             ({len(data)}) {data.hex()}")

                for pkt in conn.received_raw_packet(data):
                    print(f"[->] Response           ({len(pkt)}) {pkt.hex()}")
                    sock.sendto(pkt, addr)
                    last_send = time.time()

                if conn.b_closed:
                    print(f"[INFO] Server closed connection: {conn.close_reason or 'no reason'}")
                    break

            except socket.timeout:
                pass

            except KeyboardInterrupt:
                print("\n[INFO] Disconnecting...")
                try:
                    pkt = conn.create_disconnect_packet()
                    sock.sendto(pkt, (server_ip, server_port))
                    print(f"[->] Disconnect         ({len(pkt)}) {pkt.hex()}")
                except Exception:
                    pass
                break
            except Exception:
                traceback.print_exc()
                break

            if time.time() - last_send >= KEEPALIVE_INTERVAL:
                keepalive_packet = conn.create_empty_packet(80)
                sock.sendto(keepalive_packet, (server_ip, server_port))
                last_send = time.time()
                print("[->] Keepalive")

    finally:
        sock.close()
        print("[INFO] Connection closed")


if __name__ == "__main__":
    configure_output_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--ip", default=DEFAULT_SERVER_IP)
    p.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
    a = p.parse_args()
    main(a.ip, a.port)
