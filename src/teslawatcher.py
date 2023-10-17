import json
import os
import re
import smtplib
import ssl
import time
from datetime import datetime
from random import randint
from typing import List, Any, Tuple

import pytz
import requests
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

from src.incentives import INCENTIVES

COMMON_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9,mr-IN;q=0.8,mr;q=0.7,hi-IN;q=0.6,hi;q=0.5",
    "dnt": "1",
    "sec-ch-ua": "\"Chromium\";v=\"116\", \"Not)A;Brand\";v=\"24\", \"Google Chrome\";v=\"116\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "macOS",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/116.0.0.0 Safari/537.36"
}

CSRF_REGEX = r""".*\"csrf_key\":\"(.*?)\",\"csrf_token\":\"(.*?)\".*"""



def enrich_address(address_text):
    geolocator = Nominatim(user_agent="tesla_watcher", timeout=20)
    geocode = RateLimiter(
        geolocator.geocode, min_delay_seconds=3.0, error_wait_seconds=3.0, swallow_exceptions=False, max_retries=10)
    geolocation = geocode(address_text)
    tf = TimezoneFinder()
    timezone = tf.timezone_at(lng=geolocation.longitude, lat=geolocation.latitude)
    return round(geolocation.latitude, 5), round(geolocation.longitude, 5), timezone


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
            top_results_count: int = 5,
            max_retry_attempts: int = 5,
            timeout_seconds: int = 60,
            mailing_list_txt: str = "resources/mailing_list.txt",
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
        self.smtp_recipients = [email_id.strip() for email_id in open(mailing_list_txt) if email_id.strip()]
        self.smtp_user_email = smtp_user_email
        self.smtp_user_password = smtp_user_password
        self.can_notify = all(map(bool, [self.smtp_user_email, self.smtp_user_password, self.smtp_recipients]))

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

    def notify(self, top_results: List[List[str]], total_results: int) -> str:
        smtp_host = self.smtp_host
        sender = str(self.smtp_user_email)
        password = str(self.smtp_user_password)
        recipients = self.smtp_recipients
        can_notify = self.can_notify
        browser_url = self.tesla_browser_url

        timestamp = datetime.now(pytz.utc).astimezone(pytz.timezone(self.timezone)).strftime("%Y-%m-%dT%H:%M:%S")
        subject_line = f"Subject: Tesla @ [{timestamp}]"
        content_lines = ([f"Top {len(top_results)}/{total_results} matches from {browser_url}:", ""] +
                         [line for result in top_results for line in result])
        banner = make_banner(sender, recipients, subject_line, content_lines)
        email_message = "\n".join([subject_line] + content_lines)
        if can_notify:
            try:
                with smtplib.SMTP_SSL(smtp_host, 465, context=ssl.create_default_context()) as server:
                    server.login(sender, password)
                    server.sendmail(sender, recipients, email_message.encode("utf-8"))
            except Exception as e:
                raise IOError(f"Error notifying results: Results={banner}") from e
        else:
            print("WARNING: missing email user, password, or recipients - Will not notify results")
        return banner

    def order_identifiers(self, vin):
        url = self.tesla_order_url(vin=vin)
        headers = self.tesla_order_headers
        timeout = self.timeout_seconds
        params = self.tesla_order_params

        resp = requests.get(url=url, params=params, headers=headers, timeout=timeout)
        order_url = resp.url
        coin_auth = resp.cookies["coin_auth"]
        csrf_name, csrf_value = (
            re.match(CSRF_REGEX, resp.text, flags=(re.UNICODE | re.MULTILINE | re.DOTALL)).groups())
        return order_url, coin_auth, csrf_name, csrf_value

    def taxes_and_fees(self, model, trim, price, order_url, coin_auth, csrf_name, csrf_value):
        url = self.tesla_taxes_url
        headers = self.tesla_taxes_headers(referrer=order_url, coin_auth=coin_auth)
        timeout = self.timeout_seconds
        params = self.tesla_taxes_body(
            model=model, trim=trim, price_before_discounts=price, csrf_name=csrf_name, csrf_value=csrf_value)

        resp = requests.post(url=url, headers=headers, timeout=timeout, json=params)
        if resp.status_code == 200:
            costs = json.loads(resp.content)
            return sum(d["amount"] for d in costs["AUTO_CASH"]["fees"] + costs["AUTO_CASH"]["taxes"])
        else:
            raise IOError(f"Taxes and Fees calculator API failed: ResponseCode={resp.status_code}")

    def total_incentives(self, car):
        country, state, county, city = self.country, self.state, self.county, self.city
        return sum(
            (v if v else 0.0) for v in [incentive(car, country, state, county, city) for incentive in INCENTIVES])

    def extract(self, page: dict[str, Any]) -> Tuple[List[List[str]], int]:
        total = page["total_matches_found"]
        lines = []
        for car in page["results"]:
            odometer = float(car["Odometer"])
            odometer_unit = car["OdometerType"]
            miles = f"[{int(odometer)} {odometer_unit}]" if odometer >= 1.0 else ""
            demo = "[Demo Vehicle]" if car["IsDemo"] else ""
            model_code, trim_code = None, None
            for code in car["OptionCodeData"]:
                if code["group"] == "MODEL":
                    model_code = code["code"]
                if code["group"] == "TRIM":
                    trim_code = code["code"]
                if model_code is not None and trim_code is not None:
                    break
            else:
                if model_code is None or trim_code is None:
                    raise ValueError("Model and Trim info missing in search result")
            vin = car["VIN"]
            selling_price = car["PurchasePrice"]
            order_url, coin_auth, csrf_name, csrf_value = self.order_identifiers(vin=vin)
            total_taxes_and_fees = self.taxes_and_fees(
                model=model_code,
                trim=trim_code,
                price=selling_price,
                order_url=order_url,
                coin_auth=coin_auth,
                csrf_name=csrf_name,
                csrf_value=csrf_value
            )
            payment = selling_price + total_taxes_and_fees
            net_cost = payment - self.referral_discount - self.total_incentives(car)
            result_lines = [
                f"[${selling_price:,.2f} => ${payment:,.2f} => ${net_cost:,.2f}]{miles}{demo}",
                f'  {car["Year"]} Tesla {car["TrimName"]}'
            ]
            for spec in car["OptionCodeSpecs"]["C_SPECS"]["options"]:
                result_lines.append(f'  {spec["description"]}: {spec["name"]}')
            for opt in car["OptionCodeSpecs"]["C_OPTS"]["options"]:
                result_lines.append(f'  {opt["name"]}'.replace("’’", "''"))
            result_lines.append(f"  Order: {order_url}")
            lines.append(result_lines)
        return lines, total

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
        max_retry_attempts = self.max_retry_attempts
        while True:
            attempt += 1
            try:
                return self.notify(*self.extract(self.fetch()))
            except Exception as e:
                if attempt < max_retry_attempts:
                    print(f"Failed Attempt #{attempt}: Error={repr(e)}")
                    backoff_random()
                else:
                    raise e
