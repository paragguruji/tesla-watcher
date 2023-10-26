from typing import List


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
        self.html_page = """<html lang="en"><head></head><body><h3>
        <a href="{link}">Top {count}/{total} @ {timestamp}</a></h3>{paras}</body></html>""".replace("\n", "")
        self.html_block = """<p><h4>{name}</h4><ol>{records}</ol>"""
        self.html_long_row = """<li><b><a href="{link}">{summary}</a></b><br>{details}</li>"""
        self.html_short_row = """<li><a href="{link}">{summary}</a></li>"""
        self.plaintext_page = """Top {count}/{total} @ {timestamp}\nFrom: {link}\n\n{paras}"""
        self.plaintext_paragraph = """{name}\n\n{records}"""
        self.plaintext_row = """\t{summary}\n\t{details}\n\t{link}\n\n"""

    def format_page(self, page, block, row):
        return page.format(
            link=self.link,
            count=self.count,
            total=self.total,
            timestamp=self.timestamp,
            paras="".join([
                block.format(
                    name=name,
                    records="".join([
                        row.format(
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
    def html_long_form(self):
        return self.format_page(page=self.html_page, block=self.html_block, row=self.html_long_row)

    @property
    def html_short_form(self):
        return self.format_page(page=self.html_page, block=self.html_block, row=self.html_short_row)

    @property
    def plain_text(self):
        return self.format_page(page=self.plaintext_page, block=self.plaintext_paragraph, row=self.plaintext_row)
