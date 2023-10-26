import re
import time
from random import randint

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

REGEX_EMAIL = re.compile(
    r"^([a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*)"
    r"@((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)$",
    re.IGNORECASE | re.MULTILINE
)
REGEX_PHONE = re.compile(
    r"^(\+1)?(\s|-)?(\([1-9][0-9]{2}\)|[1-9][0-9]{2})(\s|-)?(\([0-9]{3}\)|[0-9]{3})(\s|-)?(\([0-9]{3}\)|[0-9]{4})$",
    re.MULTILINE
)
REGEX_CSRF = re.compile(r".*\"csrf_key\":\"(.*?)\",\"csrf_token\":\"(.*?)\".*", re.UNICODE | re.MULTILINE | re.DOTALL)

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
    email_list = []
    sms_list = []
    for recipient in recipients:
        recipient = recipient.strip()
        matched = REGEX_EMAIL.match(recipient)
        if matched is None:
            print(f"WARNING: invalid email: {recipient}")
            continue
        local, domain = matched.groups()
        known_sms_gateway = domain in SMS_GATEWAYS
        matched = REGEX_PHONE.match(local)
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
