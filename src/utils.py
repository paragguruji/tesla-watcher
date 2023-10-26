import re
import time
from random import randint
from typing import List

import pytz
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim
from google.cloud import storage
from timezonefinder import TimezoneFinder

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

SMS_GATEWAYS = {
    "txt.att.net": "AT&T",
    "messaging.sprintpcs.com": "SPRINT",
    "pm.sprint.com": "SPRINT",
    "tmomail.net": "TMobile",
    "vtext.com": "VERIZON",
    "myboostmobile.com": "Boost Mobile",
    "sms.mycricket.com": "Cricket",
    "mymetropcs.com": "Metro PCS",
    "mmst5.tracfone.com": "Tracfone",
    "email.uscc.net": "U.S. Cellular",
    "vmobl.com": "Virgin Mobile"
}

HTML_WRAPPER = """<html lang="en"><head></head><body><h3>
<a href="{link}">Top {count}/{total} @ {timestamp}</a></h3>{paras}</body></html>""".replace("\n", "")
HTML_PARA = """<p><h4>{name}</h4><ol>{records}</ol>"""
HTML_RECORD_LONG = """<li><b><a href="{link}">{summary}</a></b><br>{details}</li>"""
HTML_RECORD_SHORT = """<li><a href="{link}">{summary}</a></li>"""

PLAIN_WRAPPER = """Top {count}/{total} @ {timestamp}\nFrom: {link}\n\n{paras}"""
PLAIN_PARA = """{name}\n\n{records}"""
PLAIN_RECORD = """\t{summary}\n\t{details}\n\t{link}\n\n"""


class TeslaSummary:
    def __init__(self, year, demo, miles, options, price, taxes, fees, incentives, referral, order_url):
        self.demo = demo
        self.miles = miles
        self.year = f"{year}"
        self.make = "Tesla"
        self.model = f'{options["MODEL"]["name"]}'
        self.trim = f'{options["TRIM"]["name"]}'
        self.paint = f'{options["PAINT"]["name"]}'
        self.wheels = f'{options["WHEELS"]["name"]}'.replace("’’", "''")
        self.range = f'{options["SPECS_RANGE"]["value"]} {options["SPECS_RANGE"]["unit_short"]}'
        self.speed = f'{options["SPECS_TOP_SPEED"]["value"]} {options["SPECS_TOP_SPEED"]["unit_short"]}'
        self.acceleration = f'{options["SPECS_ACCELERATION"]["acceleration_value"]} '\
                            f'{options["SPECS_ACCELERATION"]["acceleration_unit_short"]} in '\
                            f'{options["SPECS_ACCELERATION"]["value"]} '\
                            f'{options["SPECS_ACCELERATION"]["unit_short"]}'
        self.interior = f'{options["INTERIOR"]["name"]}'
        self.seating = f'{options["REAR_SEATS"]["name"]}'
        self.autopilot = f'{options["AUTOPILOT"]["name"]}'
        self.price = f'${price:,.2f}'
        self.payment = f'${price + taxes + fees:,.2f}'
        self.cost = f'${price + taxes + fees - incentives - referral:,.2f}'
        self.link = f'{order_url}'

    @property
    def name(self):
        return " ".join([self.year, self.make, self.model, self.trim])


class ResultPage:
    def __init__(self, timestamp: str, total: int, link: str, cars: List[TeslaSummary]):
        self.timestamp = timestamp
        self.count = len(cars)
        self.total = total
        self.link = link
        self.paras = {}
        for car in cars:
            if car.name not in self.paras:
                self.paras[car.name] = []
            self.paras[car.name].append(car)

    def format_page(self, wrapper, para, record):
        return wrapper.format(
            link=self.link,
            count=self.count,
            total=self.total,
            timestamp=self.timestamp,
            paras="".join([
                para.format(
                    name=name,
                    records="".join([
                        record.format(
                            link=car.link,
                            summary=" | ".join(filter(bool, map(str.strip, [
                                car.demo, car.miles, car.paint, car.interior, car.cost, car.payment]))),
                            details=" | ".join(filter(bool, map(str.strip, [
                                car.wheels, car.seating, car.range, car.speed, car.acceleration, car.autopilot])))
                        )
                        for car in cars
                    ])
                )
                for (name, cars) in self.paras.items()
            ])
        )

    @property
    def subject(self):
        return f"Tesla ({self.timestamp})\n"

    @property
    def html_email(self):
        return self.format_page(wrapper=HTML_WRAPPER, para=HTML_PARA, record=HTML_RECORD_LONG)

    @property
    def html_sms(self):
        return self.format_page(wrapper=HTML_WRAPPER, para=HTML_PARA, record=HTML_RECORD_SHORT)

    @property
    def plain_text(self):
        return self.format_page(wrapper=PLAIN_WRAPPER, para=PLAIN_PARA, record=PLAIN_RECORD)


def gcp_upload_text(path: str, content: str) -> None:
    bucket, blob = path.split("/", 1)
    storage.Client().bucket(bucket).blob(blob).upload_from_string(content)


def gcp_download_text(path: str) -> str:
    bucket, blob = path.split("/", 1)
    return storage.Client().bucket(bucket).blob(blob).download_as_text()


def enrich_address(address_text):
    geolocator = Nominatim(user_agent="tesla_watcher", timeout=20)
    geocode = RateLimiter(
        geolocator.geocode, min_delay_seconds=3.0, error_wait_seconds=3.0, swallow_exceptions=False, max_retries=10)
    geolocation = geocode(address_text)
    tf = TimezoneFinder()
    timezone = pytz.timezone(tf.timezone_at(lng=geolocation.longitude, lat=geolocation.latitude))
    return round(geolocation.latitude, 5), round(geolocation.longitude, 5), timezone


def backoff_random(_min=3, _max=9):
    time.sleep(randint(_min, _max))


def parse_recipients(recipients):
    regex_email = re.compile(
        r"^([a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*)"
        r"@((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)$",
        re.IGNORECASE | re.MULTILINE
    )
    regex_cell = re.compile(
        r"^(\+1)?(\s|-)?(\([1-9][0-9]{2}\)|[1-9][0-9]{2})(\s|-)?(\([0-9]{3}\)|[0-9]{3})(\s|-)?(\([0-9]{3}\)|[0-9]{4})$",
        re.MULTILINE
    )
    email_list = []
    sms_list = []
    for recipient in recipients:
        recipient = recipient.strip()
        matched = regex_email.match(recipient)
        if matched is None:
            print(f"WARNING: invalid email: {recipient}")
            continue
        local, domain = matched.groups()
        known_sms_gateway = domain in SMS_GATEWAYS
        matched = regex_cell.match(local)
        cell_10_digit = None if matched is None else matched.group(3).strip("()") + matched.group(5) + matched.group(7)
        if known_sms_gateway and cell_10_digit:
            sms_list.append(f"{cell_10_digit}@{domain}")
        elif not known_sms_gateway and not cell_10_digit:
            email_list.append(recipient)
        elif not known_sms_gateway and cell_10_digit:
            print(f"WARNING: RECIPIENT IGNORED: unknown SMS Gateway {domain} for phone number: {local}")
        elif known_sms_gateway and not cell_10_digit:
            print(f"WARNING: RECIPIENT IGNORED: invalid phone number for {SMS_GATEWAYS[domain]} SMS Gateway: {local}")
    return email_list, sms_list
