import sys
from typing import Dict

from src import WSGI_START_RESPONSE_TYPEDEF
from src.teslawatcher import backoff_random, TeslaWatcher


def repeat(run_count=-1, interval_seconds=(60 * 60 * 3)):
    remaining = run_count
    while remaining != 0:
        remaining -= 1
        try:
            print(APP.run())
            backoff_random(interval_seconds, interval_seconds)
        except Exception as e:
            print(f"All attempts failed: Error={repr(e)}")
            backoff_random()


def app(environ: Dict[str, str], start_response: WSGI_START_RESPONSE_TYPEDEF):
    status = "200 OK"
    data = f"{APP.run()}"
    response_headers = [
        ("Content-type", "text/plain"),
        ("Content-Length", str(len(data)))
    ]
    exc_info = sys.exc_info()
    if all(e is None for e in exc_info):
        exc_info = None
    start_response(status, response_headers, exc_info)
    return iter([data.encode("utf-8")])


def simulate_wsgi_request():
    response = app(dict(), lambda x, y, z: lambda w: print(w))
    for out_line in response:
        print(out_line.decode('utf-8'))


if __name__ == "__main__":
    APP = TeslaWatcher(
        street="1245 Main St",
        city="Rahway",
        county="Union",
        state="NJ",
        country="US",
        zipcode="07065",
        model="my",
        trim="LRAWD"
    )
    repeat(run_count=1)
