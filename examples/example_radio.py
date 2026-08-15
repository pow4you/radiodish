"""
Run a RADIO that broadcasts fake sensor readings on two groups: "temp" and
"humidity". Run this alongside example_dish.py.

Usage:
    python3 example_radio.py [--bind-port 9000] [--dish host:port ...]

By default it binds to 127.0.0.1:9000 and connects to a dish at
127.0.0.1:9001 (start example_dish.py with --bind-port 9001 first, or in
either order — RADIO also auto-registers any dish that JOINs it).
"""
import argparse
import asyncio
import random

from radish import RadioSocket


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind-port", type=int, default=9000)
    parser.add_argument("--dish", action="append", default=[],
                         help="host:port of a dish to connect() to, repeatable")
    args = parser.parse_args()

    dishes = args.dish or ["127.0.0.1:9001"]

    radio = await RadioSocket().bind("127.0.0.1", args.bind_port)
    for d in dishes:
        host, port = d.split(":")
        radio.connect(host, int(port))

    print(f"[radio] bound on 127.0.0.1:{args.bind_port}, connected to {dishes}")

    try:
        while True:
            temp = round(20 + random.random() * 5, 1)
            humidity = round(40 + random.random() * 20, 1)
            await radio.send(f"{temp}C".encode(), group="temp")
            await radio.send(f"{humidity}%".encode(), group="humidity")
            print(f"[radio] sent temp={temp}C humidity={humidity}%")
            await asyncio.sleep(1.0)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await radio.close()


if __name__ == "__main__":
    asyncio.run(main())
