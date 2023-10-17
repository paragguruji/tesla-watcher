

def federal_us(car, country, state, county, city):
    if country == "US" and int(car["PurchasePrice"]) < 55000:
        return 7500


def state_nj(car, country, state, county, city):
    if country == "US" and state == "NJ":
        if int(car["PurchasePrice"]) < 45000:
            return 4000
        if int(car["PurchasePrice"]) < 55000:
            return 1500


def state_ny(car, country, state, county, city):
    if country == "US" and state == "NY":
        if int(car["PurchasePrice"]) < 42000:
            return 2000
        if int(car["PurchasePrice"]) < 80000:
            return 500


INCENTIVES = [federal_us, state_nj, state_ny]
