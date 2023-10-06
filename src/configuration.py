import json
import os
from types import TracebackType
from typing import Callable, List, Tuple, Optional, Type

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

MAX_ATTEMPTS = 5

TIMEOUT_SEC = 60

INTERVAL_SEC = 60 * 60 * 3

BROWSER_URL = "https://www.tesla.com/inventory/new/my?TRIM=LRAWD&arrangeby=plh&zip=07065&range=0"

API_URL = "https://www.tesla.com/inventory/api/v1/inventory-results"

HEADERS = {
    "authority": "www.tesla.com",
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9,mr-IN;q=0.8,mr;q=0.7,hi-IN;q=0.6,hi;q=0.5",
    "dnt": "1",
    "referer": BROWSER_URL,
    "sec-ch-ua": "\"Chromium\";v=\"116\", \"Not)A;Brand\";v=\"24\", \"Google Chrome\";v=\"116\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "macOS",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/116.0.0.0 Safari/537.36"
}

URL_PARAMS = {
    "query": json.dumps(
        {
            "query": {
                "model": "my",
                "condition": "new",
                "options": {
                    "TRIM": [
                        "LRAWD"
                    ]
                },
                "arrangeby": "Price",
                "order": "asc",
                "market": "US",
                "language": "en",
                "super_region": "north america",
                "lng": -74.2824862,
                "lat": 40.6041777,
                "zip": "07065",
                "range": 0,
                "region": "NJ"
            },
            "offset": 0,
            "count": 5,
            "outsideOffset": 0,
            "outsideSearch": False
        },
        indent=None,
        separators=(",", ":")
    )
}

SENDER = os.environ["SMTP_USER_EMAIL"]

PASSWORD = os.environ["SMTP_USER_PASSWORD"]

RECIPIENTS = [email_id.strip() for email_id in open("resources/mailing_list.txt") if email_id.strip()]

WSGI_START_RESPONSE_TYPEDEF = Callable[
    [str,
     List[Tuple[str, str]],
     Optional[tuple[Type[BaseException], BaseException, TracebackType] | tuple[None, None, None]]],
    Callable[[bytes], None]
]
