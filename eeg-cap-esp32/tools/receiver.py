#!/usr/bin/env python3
"""
Connects to the ESP32 EEG firmware's TCP stream, decodes sample frames,
and live-plots all 8 channels (stacked, EEG-style). Optionally logs to CSV.

Frame format (must match firmware/src/main.cpp):
    [0]      0xA0 marker byte
    [1..4]   uint32 little-endian sample counter
    [5..36]  8 x float32 little-endian, microvolts

Usage:
    python receiver.py --host 192.168.1.42 --port 3399
    python receiver.py --host 192.168.1.42 --csv session.csv
"""
import argparse
import csv
import queue
import socket
import struct
import sys
import threading
from collections import deque

import matplotlib.pyplot as plt
import matplotlib.animation as animation

NUM_CHANNELS = 8
FRAME_MARKER = 0xA0
FRAME_SIZE = 1 + 4 + NUM_CHANNELS * 4
FRAME_FORMAT = "<I" + "f" * NUM_CHANNELS  # counter, ch1..ch8 (marker byte stripped)

WINDOW_SECONDS = 5
SAMPLE_RATE_HZ = 250  # must match ads.setSampleRateCode() in firmware


def read_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Socket closed by ESP32")
        buf.extend(chunk)
    return bytes(buf)


def read_frame(sock: socket.socket):
    """Reads one frame, resyncing on the marker byte if the stream is misaligned."""
    while True:
        marker = read_exact(sock, 1)[0]
        if marker == FRAME_MARKER:
            break
    payload = read_exact(sock, FRAME_SIZE - 1)
    counter, *channels = struct.unpack(FRAME_FORMAT, payload)
    return counter, channels


def reader_thread(sock: socket.socket, out_queue: "queue.Queue", stop_event: threading.Event):
    try:
        while not stop_event.is_set():
            frame = read_frame(sock)
            out_queue.put(frame)
    except (ConnectionError, OSError):
        out_queue.put(None)  # signal EOF to the plotting side


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="ESP32 IP address")
    parser.add_argument("--port", type=int, default=3399)
    parser.add_argument("--csv", help="optional path to log samples as CSV")
    args = parser.parse_args()

    print(f"Connecting to {args.host}:{args.port} ...")
    sock = socket.create_connection((args.host, args.port), timeout=10)
    sock.settimeout(None)  # blocking mode; the reader thread owns this socket
    print("Connected. Streaming...")

    csv_writer = None
    csv_file = None
    if args.csv:
        csv_file = open(args.csv, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["counter"] + [f"ch{i+1}_uV" for i in range(NUM_CHANNELS)])

    frame_queue: "queue.Queue" = queue.Queue()
    stop_event = threading.Event()
    thread = threading.Thread(target=reader_thread, args=(sock, frame_queue, stop_event), daemon=True)
    thread.start()

    window_len = WINDOW_SECONDS * SAMPLE_RATE_HZ
    buffers = [deque([0.0] * window_len, maxlen=window_len) for _ in range(NUM_CHANNELS)]

    fig, ax = plt.subplots(figsize=(10, 6))
    offset_step = 200.0  # uV between stacked channel traces
    lines = [ax.plot([], [])[0] for _ in range(NUM_CHANNELS)]
    ax.set_xlim(0, window_len)
    ax.set_ylim(-offset_step, offset_step * NUM_CHANNELS)
    ax.set_yticks([i * offset_step for i in range(NUM_CHANNELS)])
    ax.set_yticklabels([f"CH{i+1}" for i in range(NUM_CHANNELS)])
    ax.set_xlabel("samples")
    ax.set_title("EEG live stream")

    def update(_frame):
        while True:
            try:
                item = frame_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                print("Connection closed.", file=sys.stderr)
                plt.close(fig)
                return lines
            counter, channels = item
            for i, v in enumerate(channels):
                buffers[i].append(v)
            if csv_writer:
                csv_writer.writerow([counter] + channels)
        for i, line in enumerate(lines):
            ys = [v + i * offset_step for v in buffers[i]]
            line.set_data(range(len(ys)), ys)
        return lines

    ani = animation.FuncAnimation(fig, update, interval=50, blit=True, cache_frame_data=False)
    try:
        plt.show()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        sock.close()
        if csv_file:
            csv_file.close()


if __name__ == "__main__":
    try:
        main()
    except ConnectionError as e:
        print(f"Connection error: {e}", file=sys.stderr)
        sys.exit(1)
