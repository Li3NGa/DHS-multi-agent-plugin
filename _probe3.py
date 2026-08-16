import os
import pathlib
import time

p = pathlib.Path("_probe_delay")
p.mkdir(exist_ok=True)
for delay in (0, 2, 5, 10, 15, 20):
    try:
        n = len(list(os.scandir(p)))
        print("delay", delay, "OK", n)
    except Exception as e:
        print("delay", delay, "FAIL", repr(e))
    time.sleep(delay)
