import datetime
import os
import re
# import shutil
import smtplib
import ssl
import sys
import time
from types import TracebackType
from typing import List, Optional, Dict, Callable, Tuple, Type

from bs4 import BeautifulSoup, element
from selenium import webdriver

PRICE_ADJUSTMENT = sum(v for v in dict(
    DESTINATION_FEE=1390,
    ORDER_FEE=250,
    TITLE_FEE=60,
    REGISTRATION_FEE=311,
    FILING_FEE=12,
    FEDERAL_INCENTIVE=-7500,
    STATE_INCENTIVE=-1500,
    REFERRAL=-500
).values())

WSGI_START_RESPONSE_TYPEDEF = Callable[
    [str,
     List[Tuple[str, str]],
     Optional[tuple[Type[BaseException], BaseException, TracebackType] | tuple[None, None, None]]],
    Callable[[bytes], None]
]


class TeslaWatcher(object):
    def __init__(self, url: str, timeout_sec: int, app_email: str, app_password: str, emails: List[str], limit: int):
        self._url = url
        self._timeout_sec = timeout_sec
        self._app_email = app_email
        self._app_password = app_password
        self._target_emails = emails
        self._limit = limit

    def fetch(self) -> str:
        url = self._url
        timeout_sec = self._timeout_sec
        web_driver = None
        try:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-browser-side-navigation")
            # chrome_options.add_argument(f"--user-data-dir=./tmp")
            chrome_options.add_argument("--ignore-certificate-errors")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument(f"--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
                                        f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.50 Safari/537.36")
            chrome_options.page_load_strategy = "normal"
            web_driver = webdriver.Chrome(options=chrome_options)
            web_driver.set_page_load_timeout(timeout_sec)
            web_driver.get(url)
            return web_driver.page_source
        except Exception as e:
            raise IOError(f"Error fetching inventory: URL={url}") from e
        finally:
            if web_driver is not None:
                web_driver.quit()
            # shutil.rmtree("./tmp")

    def extract(self, html: Optional[str]) -> Tuple[List[List[str]], int]:
        def parse_one(car_html: element.Tag) -> List[str]:
            name = (
                car_html
                .select_one("section.result-header")
                .select_one("div.result-basic-info")
                .select_one("div.tds-text_color--10")
                .text
            )
            price = (
                car_html
                .select_one("section.result-header")
                .select_one("div.result-pricing")
                .select_one("div.result-price")
                .select_one("div.result-loan-payment")
                .select_one("span.result-purchase-price")
                .text
            )
            named_features = [
                (item.select_one("div.tds-text--caption").select_one("span").text + ": " +
                 item.select_one("div").select_one("span.tds-text--h4").text +
                 item.select_one("div").find(name="span", attrs={"class": ""}).text
                 )
                for item in car_html
                .select_one("section.result-highlights-cta")
                .select_one("div.result-highlights")
                .select_one("ul.highlights-list")
                .select("li")
            ]
            unnamed_features = [_.text.replace("’", "'") for _ in (
                car_html
                .select_one("section.result-features.features-grid")
                .select_one("ul.result-regular-features")
                .select("li.tds-list-item")
            )]
            price = float(re.sub(r"[^0-9.]", "", price))
            return (
                [f"[${price:,.2f} => ${(price + PRICE_ADJUSTMENT):,.2f}]"] +
                [f"  {v}" for v in [name] + named_features + unnamed_features] +
                [""]
            )

        if html is None:
            html = ""
        url = self._url
        limit = self._limit
        try:
            cars = (
                BeautifulSoup(markup=html, features="html.parser")
                .find(name="body")
                .find(name="div", attrs={"id": "iso-container"})
                .find(name="main")
                .find(name="div", attrs={"class": "results-container"})
                .find_all(name="article", attrs={"class": "result card"})
            )
        except Exception as e:
            raise RuntimeError(f"Error parsing inventory: ContentLength={len(html)} URL={url} head={html[:500]}") from e
        else:
            results = []
            found = len(cars)
            for idx, car in enumerate(cars, start=1):
                if idx > limit:
                    break
                try:
                    results.append(parse_one(car))
                except Exception as e:
                    raise RuntimeError(f"Error parsing Car #{idx}/{len(cars)}: URL={url} HTML={car}") from e
        return results, found

    def notify(self, top_results: List[List[str]], total_results: int) -> str:

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

        url = self._url
        sender = self._app_email
        password = self._app_password
        recipients = self._target_emails
        subject_line = "Subject: Tesla @ [{}]".format(datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
        content_lines = (
            [f"Top {len(top_results)}/{total_results} matches ({url}):", ""] +
            [line for result in top_results for line in result]
        )
        banner = make_banner(sender, recipients, subject_line, content_lines)
        email_message = "\n".join([subject_line] + content_lines)
        if recipients:
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
                    server.login(sender, password)
                    server.sendmail(sender, recipients, email_message.encode("utf-8"))
            except Exception as e:
                raise IOError(f"Error notifying results: Results={banner}") from e
        return banner

    def run(self) -> str:
        attempt = 0
        while attempt < 5:
            attempt += 1
            try:
                return self.notify(*self.extract(self.fetch()))
            except Exception as e:
                print(f"Failed Attempt #{attempt}: Error={repr(e)}")


def local_main(tesla_watcher: TeslaWatcher, interval_sec: int):
    done = False
    while True:
        if done:
            time.sleep(interval_sec)
        done = tesla_watcher.run()


def app(environ: Dict[str, str], start_response: WSGI_START_RESPONSE_TYPEDEF):
    overridden_environ = os.environ.copy()
    overridden_environ.update(environ)
    _interval_sec = 60 * 60
    _timeout_sec = 60
    _url = "https://www.tesla.com/inventory/new/my?TRIM=LRAWD&arrangeby=plh&zip=07065&range=0"
    _app_email = overridden_environ["SMTP_USER_EMAIL"]
    _app_password = overridden_environ["SMTP_USER_PASSWORD"]
    _target_emails = [email_id.strip() for email_id in open("resources/mailing_list.txt") if email_id.strip()]
    _max_results = 3
    _watcher = TeslaWatcher(
        url=_url,
        timeout_sec=_timeout_sec,
        app_email=_app_email,
        app_password=_app_password,
        emails=_target_emails,
        limit=_max_results
    )
    status = "200 OK"
    data = f"{_watcher.run()}"
    response_headers = [
        ("Content-type", "text/plain"),
        ("Content-Length", str(len(data)))
    ]
    exc_info = sys.exc_info()
    if all(e is None for e in exc_info):
        exc_info = None
    start_response(status, response_headers, exc_info)
    return iter([data.encode("utf-8")])


if __name__ == "__main__":
    response = app(dict(), lambda x, y, z: lambda w: print(w))
    for out_line in response:
        print(out_line.decode('utf-8'))
