import datetime
import os
import re
import shutil
import smtplib
import ssl
import time
from typing import List, Optional

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


class TeslaWatcher:
    def __init__(self, url, timeout_sec, app_email, app_password, target_emails, max_results):
        self._url = url
        self._timeout_sec = timeout_sec
        self._app_email = app_email
        self._app_password = app_password
        self._target_emails = target_emails
        self._max_results = max_results

    def fetch(self):
        url = self._url
        timeout_sec = self._timeout_sec
        web_driver = None
        try:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-browser-side-navigation")
            chrome_options.add_argument(f"--user-data-dir=./tmp")
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
            print(f"Error fetching inventory from: {url} \n Error: {e}")
        finally:
            if web_driver is not None:
                web_driver.quit()
            shutil.rmtree("./tmp")

    def extract(self, inventory_html: Optional[str]):
        def parse_one(car_html: element.Tag):
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
            unnamed_features = [_.text for _ in (
                car_html
                .select_one("section.result-features.features-grid")
                .select_one("ul.result-regular-features")
                .select("li.tds-list-item")
            )]
            price = float(re.sub(r"[^0-9.]", "", price))
            cost = price + PRICE_ADJUSTMENT
            return "\n\t".join([f"[${price:,.2f} => ${cost:,.2f}]", name] + named_features + unnamed_features)

        if inventory_html is None:
            inventory_html = ""
        url = self._url
        try:
            cars = (
                BeautifulSoup(markup=inventory_html, features="html.parser")
                .find(name="body")
                .find(name="div", attrs={"id": "iso-container"})
                .find(name="main")
                .find(name="div", attrs={"class": "results-container"})
                .find_all(name="article", attrs={"class": "result card"})
            )
        except Exception as e:
            print(f"Error parsing inventory: {e}\nContentLength={len(inventory_html)}\nURL={url}")
        else:
            results = []
            for idx, car in enumerate(cars):
                try:
                    results.append(parse_one(car))
                except Exception as e:
                    print(f"Error parsing car #{idx + 1}/{len(cars)}: {e}\nResultCardHTML=\n{car}\nURL={url}")
            return results

    def notify(self, results: Optional[List[str]]):
        def print_banner():
            header = ["", f"From: <{sender}>", "To: " + ",".join([f"<{r}>" for r in recipients]), subject_line, ""]
            body = [""] + content_lines + [""]
            width = (10 + max(map(len, header + content_lines)))
            print("\n".join(
                ["+" + "=" * width + "+"] +
                ["|" + line + (" " * (width - len(line))) + "|" for line in header] +
                ["+" + "-" * width + "+"] +
                ["|" + line + (" " * (width - len(line))) + "|" for line in body] +
                ["+" + "=" * width + "+"]
            ))

        if results is None:
            return False
        url = self._url
        sender = self._app_email
        password = self._app_password
        recipients = self._target_emails
        limit = self._max_results
        subject_line = "Subject: Tesla @ [{}]".format(datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
        content_lines = [f"Top {min(limit, len(results))}/{len(results)} matches ({url}):"] + results[:limit]
        print_banner()
        if recipients:
            try:
                with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
                    server.login(sender, password)
                    server.sendmail(sender, recipients, "\n\n".join([subject_line] + content_lines).encode("utf-8"))
            except Exception as e:
                print(f"Error notifying results: {e}")
                return False
        return True

    def run(self):
        return self.notify(self.extract(self.fetch()))


def local_main(tesla_watcher: TeslaWatcher, interval_sec: int):
    done = False
    while True:
        if done:
            time.sleep(interval_sec)
        done = tesla_watcher.run()


if __name__ == "__main__":
    _interval_sec = 60 * 60
    _timeout_sec = 60
    _url = "https://www.tesla.com/inventory/new/my?TRIM=LRAWD&arrangeby=plh&zip=07065&range=0"
    _app_email = os.environ["SMTP_USER_EMAIL"]
    _app_password = os.environ["SMTP_USER_PASSWORD"]
    _target_emails = [email_id.strip() for email_id in open("resources/mailing_list.txt") if email_id.strip()]
    _max_results = 3
    _watcher = TeslaWatcher(
        url=_url,
        timeout_sec=_timeout_sec,
        app_email=_app_email,
        app_password=_app_password,
        target_emails=_target_emails,
        max_results=_max_results
    )
    _watcher.run()
    # local_main(_watcher, _interval_sec)
