import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Any, Tuple

import pytz
import requests

from src.incentives import INCENTIVES
from src.tesla_results import TeslaSummary, ResultPage
from src.utils import enrich_address, COMMON_HEADERS, REGEX_CSRF, backoff_random, \
    parse_recipients, gcp_download_text, gcp_upload_text

GCP_BUCKET = "develop_pguruji_static_resources"
GCP_PATH_MAILING_LIST = "tesla_watcher/mailing_list.txt"
GCP_PATH_SEARCH_RESULT = "tesla_watcher/last_results.txt"


class TeslaWatcher:
    def __init__(
            self,
            street: str,
            city: str,
            county: str,
            state: str,
            country: str,
            zipcode: str,
            model: str,
            trim: str,
            referral_discount: float = 500.0,
            top_results_count: int = 10,
            max_retry_attempts: int = 5,
            timeout_seconds: int = 60,
            mailing_list_path: str = f"{GCP_BUCKET}/{GCP_PATH_MAILING_LIST}",
            last_results_path: str = f"{GCP_BUCKET}/{GCP_PATH_SEARCH_RESULT}",
            smtp_host: str = "smtp.gmail.com",
            smtp_user_email: str = os.environ.get("SMTP_USER_EMAIL", None),
            smtp_user_password: str = os.environ.get("SMTP_USER_PASSWORD", None)
    ):
        # Address
        self.street = street
        self.city = city
        self.county = county
        self.state = state
        self.country = country
        self.zipcode = zipcode
        self.address_text = ", ".join([line for line in [
            street, city, (county if county.lower().endswith("county") else county.strip() + " County"),
            state, country, zipcode] if line])
        self.latitude, self.longitude, self.timezone = enrich_address(address_text=self.address_text)

        # Tesla
        self.model = model
        self.trim = trim
        self.referral_discount = referral_discount

        # Operational
        self.top_results_count = top_results_count
        self.max_retry_attempts = max_retry_attempts
        self.timeout_seconds = timeout_seconds

        # Notification
        self.smtp_host = smtp_host
        self.smtp_user = smtp_user_email
        self.smtp_password = smtp_user_password
        self.email_recipients, self.sms_recipients = parse_recipients(gcp_download_text(mailing_list_path).split("\n"))
        self.need_email = all(map(bool, [self.smtp_user, self.smtp_password, self.email_recipients]))
        self.need_sms = all(map(bool, [self.smtp_user, self.smtp_password, self.sms_recipients]))
        self.last_results_path = last_results_path

    @property
    def tesla_browser_url(self):
        return (f"https://www.tesla.com/inventory/new/{self.model}?"
                f"TRIM={self.trim}&arrangeby=plh&zip={self.zipcode}&range=0")

    @property
    def tesla_search_url(self):
        return "https://www.tesla.com/inventory/api/v1/inventory-results"

    @property
    def tesla_search_headers(self):
        return COMMON_HEADERS | {"authority": "www.tesla.com", "referer": self.tesla_browser_url}

    @property
    def tesla_search_params(self):
        return {
            "query": json.dumps(
                {
                    "query": {
                        "model": self.model,
                        "condition": "new",
                        "options": {
                            "TRIM": [
                                self.trim
                            ]
                        },
                        "arrangeby": "Price",
                        "order": "asc",
                        "market": self.country,
                        "language": "en",
                        "lng": self.latitude,
                        "lat": self.longitude,
                        "zip": self.zipcode,
                        "range": 0,
                        "region": self.state
                    },
                    "offset": 0,
                    "count": self.top_results_count,
                    "outsideOffset": 0,
                    "outsideSearch": False
                },
                indent=None,
                separators=(",", ":")
            )
        }

    def tesla_order_url(self, vin):
        return (f"https://www.tesla.com/{self.model}/order/{vin}?"
                f"postal={self.zipcode}&region={self.state}&coord={self.latitude},{self.longitude}")

    @property
    def tesla_order_params(self):
        return {
            "postal": self.zipcode,
            "region": self.state,
            "coord": f"{self.latitude},{self.longitude}"
        }

    @property
    def tesla_order_headers(self):
        return self.tesla_search_headers

    @property
    def tesla_taxes_url(self):
        return "https://www.tesla.com/configurator/api/v3/fees-taxes-calculator"

    # noinspection PyMethodMayBeStatic
    def tesla_taxes_headers(self, referrer, coin_auth):
        return COMMON_HEADERS | {
            "authority": "www.tesla.com",
            "origin": "www.tesla.com",
            "content-type": "application/json",
            "referer": referrer,
            "cookie": f"coin_auth={coin_auth}",
        }

    def tesla_taxes_body(self, model, trim, price_before_discounts, csrf_name, csrf_value):
        return {
            "country": self.country,
            "city": self.city,
            "state": self.state,
            "postalCode": self.zipcode,
            "basePrice": 0,
            "vehiclePrice": int(price_before_discounts),
            "modelCode": model,
            "trimCode": trim,
            f"{csrf_name}": f"{csrf_value}",
            "csrf_name": f"{csrf_name}",
            "csrf_value": f"{csrf_value}"
        }

    def smtp_send(self, channel, recipients, subject_line, html_body):
        try:
            for recipient in recipients:
                msg = MIMEMultipart()
                msg['From'] = self.smtp_user
                msg['To'] = recipient
                msg['Subject'] = subject_line
                msg.attach(MIMEText(html_body, 'html'))
                with smtplib.SMTP(host=self.smtp_host, port=587) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.smtp_user, recipients, msg.as_string())
        except Exception as e:
            raise IOError(f"Error notifying results: Channel={channel}") from e

    def notify(self, top_results: List[TeslaSummary], results: int) -> None:
        timestamp = datetime.now(pytz.utc).astimezone(self.timezone).strftime("%b %d, %I %p").replace(" 0", " ")
        results_page = ResultPage(timestamp=timestamp, total=results, link=self.tesla_browser_url, cars=top_results)
        curr = results_page.plain_text.split("\n")
        print(f"Search Results:\n{results_page.plain_text}")
        # noinspection PyBroadException
        try:
            prev = gcp_download_text(self.last_results_path).split("\n")
        except Exception as e:
            print(f"Couldn't read last results: {e}")
            prev = []
        no_change = len(curr) == len(prev) and all([curr[i] == prev[i] for i in range(1, len(prev))])
        if no_change:
            print(f'INFO: No change as of {curr[0].split("@")[1].strip()} since {prev[0].split("@")[1].strip()}')
        if not (self.need_email or self.need_sms):
            print("WARNING: missing email user, password, or recipients - Will not notify results")
        if self.need_email:
            subject = results_page.subject + (f' - No Change ({prev[0].split("@")[1]})' if no_change else "")
            self.smtp_send("EMAIL", self.email_recipients, subject, results_page.html_long_form)
        if self.need_sms and not no_change:
            self.smtp_send("SMS", self.sms_recipients, results_page.subject, results_page.html_short_form)
        gcp_upload_text(path=self.last_results_path, content=results_page.plain_text)

    def order_identifiers(self, vin):
        url = self.tesla_order_url(vin=vin)
        headers = self.tesla_order_headers
        timeout = self.timeout_seconds
        params = self.tesla_order_params

        resp = requests.get(url=url, params=params, headers=headers, timeout=timeout)
        order_url = resp.url
        coin_auth = resp.cookies["coin_auth"]
        csrf_name, csrf_value = REGEX_CSRF.match(resp.text).groups()
        return order_url, coin_auth, csrf_name, csrf_value

    def taxes_and_fees(self, model, trim, price, order_url, coin_auth, csrf_name, csrf_value) -> Tuple[float, float]:
        url = self.tesla_taxes_url
        headers = self.tesla_taxes_headers(referrer=order_url, coin_auth=coin_auth)
        timeout = self.timeout_seconds
        params = self.tesla_taxes_body(
            model=model, trim=trim, price_before_discounts=price, csrf_name=csrf_name, csrf_value=csrf_value)

        resp = requests.post(url=url, headers=headers, timeout=timeout, json=params)
        if resp.status_code == 200:
            costs = json.loads(resp.content)
            return (sum(float(d["amount"]) for d in costs["AUTO_CASH"]["taxes"]),
                    sum(float(d["amount"]) for d in costs["AUTO_CASH"]["fees"]))
        else:
            raise IOError(f"Taxes and Fees calculator API failed: ResponseCode={resp.status_code}")

    def total_incentives(self, car):
        return sum((v if v else 0.0)
                   for v in [inc(car, self.country, self.state, self.county, self.city) for inc in INCENTIVES])

    def extract(self, page: dict[str, Any]) -> Tuple[List[TeslaSummary], int]:
        total = page["total_matches_found"]
        top_cars = []
        for car in page["results"]:
            vin = car["VIN"]
            order_url, coin_auth, csrf_name, csrf_value = self.order_identifiers(vin=vin)
            price = car["PurchasePrice"]
            options = {code["group"]: code for code in car["OptionCodeData"]}
            taxes, fees = self.taxes_and_fees(
                model=options["MODEL"]["code"],
                trim=options["TRIM"]["code"],
                price=price,
                order_url=order_url,
                coin_auth=coin_auth,
                csrf_name=csrf_name,
                csrf_value=csrf_value
            )
            incentives = self.total_incentives(car)
            top_cars.append(TeslaSummary(
                year=car["Year"],
                demo=("[DEMO]" if car["IsDemo"] else ""),
                miles=(f'[{car["Odometer"]} {car["OdometerType"]}]' if car["Odometer"] else ""),
                options=options,
                price=price,
                taxes=taxes,
                fees=fees,
                incentives=incentives,
                referral=self.referral_discount,
                order_url=order_url
            ))
        return top_cars, total

    def fetch(self):
        url = self.tesla_search_url
        params = self.tesla_search_params
        headers = self.tesla_search_headers
        timeout_seconds = self.timeout_seconds
        try:
            resp = requests.get(url=url, params=params, headers=headers, timeout=timeout_seconds)
            if resp.status_code == 200:
                return json.loads(resp.content)
            raise IOError(f"ResponseCode={resp.status_code}")
        except Exception as e:
            pr = requests.Request(method="GET", url=url, params=params, headers=headers).prepare()
            raise IOError(f"Failed to fetch: URL={pr.url} headers={pr.headers}") from e

    def run(self):
        attempt = 0
        max_retry_attempts = 1  # self.max_retry_attempts
        while True:
            attempt += 1
            try:
                self.notify(*self.extract(self.fetch()))
                break
            except Exception as e:
                if attempt < max_retry_attempts:
                    print(f"Failed Attempt #{attempt}: Error={repr(e)}")
                    backoff_random()
                else:
                    raise e
