from datetime import datetime
import json
import smtplib
import ssl
import sys
import time
from random import randint
from typing import List, Dict, Tuple, Any

import pytz
import requests

from src.configuration import PRICE_ADJUSTMENT, URL_PARAMS, API_URL, MAX_ATTEMPTS, HEADERS, SENDER, RECIPIENTS, \
    PASSWORD, BROWSER_URL, INTERVAL_SEC, WSGI_START_RESPONSE_TYPEDEF


def backoff_random(_min=3, _max=9):
    time.sleep(randint(_min, _max))


def make_banner(from_email: str, to_emails: List[str], subject: str, content: List[str]) -> str:
    header = [f"From: <{from_email}>", "To: " + ",".join([f"<{r}>" for r in to_emails]), subject]
    width = (10 + max(map(len, header + content)))
    return ("\n".join(
        ["+" + "=" * width + "+"] +
        ["|" + line + (" " * (width - len(line))) + "|" for line in header] +
        ["+" + "-" * width + "+"] +
        ["|" + line + (" " * (width - len(line))) + "|" for line in content] +
        ["+" + "=" * width + "+"]
    ))


def notify(top_results: List[List[str]], total_results: int) -> str:
    timestamp = datetime.now(pytz.utc).astimezone(pytz.timezone('America/New_York')).strftime("%Y-%m-%dT%H:%M:%S")
    subject_line = f"Subject: Tesla @ [{timestamp}]"
    content_lines = ([f"Top {len(top_results)}/{total_results} matches from {BROWSER_URL}:", ""] +
                     [line for result in top_results for line in result])
    banner = make_banner(SENDER, RECIPIENTS, subject_line, content_lines)
    email_message = "\n".join([subject_line] + content_lines)
    if RECIPIENTS:
        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
                server.login(SENDER, PASSWORD)
                server.sendmail(SENDER, RECIPIENTS, email_message.encode("utf-8"))
        except Exception as e:
            raise IOError(f"Error notifying results: Results={banner}") from e
    return banner


def extract(page: dict[str, Any]) -> Tuple[List[List[str]], int]:
    total = page["total_matches_found"]
    lines = []
    for car in page["results"]:
        price = car["InventoryPrice"]
        car_lines = [
            f"[${price:,.2f} => ${(price + PRICE_ADJUSTMENT):,.2f}]",
            f'  {car["Year"]} Tesla {car["TrimName"]}'
        ]
        for spec in car["OptionCodeSpecs"]["C_SPECS"]["options"]:
            car_lines.append(f'  {spec["description"]}: {spec["name"]}')
        for opt in car["OptionCodeSpecs"]["C_OPTS"]["options"]:
            car_lines.append(f'  {opt["name"]}'.replace("’’", "''"))
        lines.append(car_lines)
    return lines, total


def fetch() -> dict[str, Any]:
    try:
        resp = requests.get(API_URL, params=URL_PARAMS, headers=HEADERS, timeout=60)
        if resp.status_code == 200:
            return json.loads(resp.content)
        raise IOError(f"ResponseCode={resp.status_code}")
    except Exception as e:
        pr = requests.Request(method="GET", url=API_URL, params=URL_PARAMS, headers=HEADERS).prepare()
        raise IOError(f"Failed to fetch: URL={pr.url} headers={pr.headers}") from e


def run():
    attempt = 0
    while True:
        attempt += 1
        try:
            return notify(*extract(fetch()))
        except Exception as e:
            if attempt < MAX_ATTEMPTS:
                print(f"Failed Attempt #{attempt}: Error={repr(e)}")
                backoff_random()
            else:
                raise e


def never_stop():
    while True:
        try:
            print(run())
            backoff_random(INTERVAL_SEC, INTERVAL_SEC)
        except Exception as e:
            print(f"All attempts failed: Error={repr(e)}")
            backoff_random()


def app(environ: Dict[str, str], start_response: WSGI_START_RESPONSE_TYPEDEF):
    status = "200 OK"
    data = f"{run()}"
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
    print(run())
