import logging
from json import loads as json_loads
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup
from requests import get

headers = {
    "Host": "www.flightaware.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"
}


def get_flight_ident(flight_number, date_time: Optional[datetime] = None):
    """
    Get the flight identifier from FlightAware.
    
    :param flight_number: The flight number to search for.
    :param date_time: Optional datetime to search for a specific flight instance.
    :return: The flight identifier, or None if not found.
    """
    omnisearch_url = "https://www.flightaware.com/ajax/ignoreall/omnisearch/flight.rvt"
    omnisearch_params = {
        "v": "50",
        "locale": "en_US",
        "searchterm": flight_number,
        "q": flight_number
    }
    resp = get(omnisearch_url, params=omnisearch_params, headers=headers)
    if resp.status_code != 200:
        logging.error(f"Failed to fetch ident from omnisearch for {flight_number}: {resp.status_code}")
        return None

    data = resp.json()
    if not data.get("data") or not len(data["data"]):
        logging.info(f"No ident found for {flight_number} via omnisearch.")
        return None
    return data["data"][0]["ident"]


def get_flight_data(ident, date_time: Optional[datetime] = None):
    """
    Get flight data from FlightAware.
    
    :param ident: The flight identifier.
    :param date_time: Optional datetime to search for a specific flight instance.
    :return: Dictionary containing flight data, or None if not found.
    """
    # Always use the regular live flight page, which contains recent/scheduled flights
    # We'll filter by date/time later if specified
    url = f"https://www.flightaware.com/live/flight/{ident}"
    if date_time:
        date_str = date_time.strftime("%Y%m%d")
        logging.info(f"Fetching flight data for {ident} (filtering for {date_str})")
    
    flight_page = get(url, headers=headers)
    if flight_page.status_code == 200:
        soup = BeautifulSoup(flight_page.text, "html.parser")
        script = soup.find("script", string=lambda text: text and "var trackpollBootstrap" in text)
        if not script:
            logging.info(f"No trackpollBootstrap script found for {ident} at {url}")
            return None
        if script:
            script_content = script.string.replace("var trackpollBootstrap = ", "", 1)
            script_content = script_content[::-1].replace(";", "", 1).strip()[::-1]
            flight_data_json = json_loads(script_content)
            flights = flight_data_json.get("flights", {})
            
            if not flights:
                logging.info(f"No flight data found for {ident}")
                return None
            
            # Get the first flight (or the one matching the time if specified)
            flight_data = None
            if date_time and len(flights) > 1:
                # Try to find the flight that best matches the requested time
                target_timestamp = date_time.timestamp()
                best_match = None
                min_diff = float('inf')
                
                for fd in flights.values():
                    dep_time = fd.get("takeoffTimes", {}).get("scheduled")
                    if dep_time:
                        diff = abs(dep_time - target_timestamp)
                        if diff < min_diff:
                            min_diff = diff
                            best_match = fd
                
                if best_match:
                    flight_data = best_match
                else:
                    flight_data = list(flights.values())[0]
            else:
                flight_data = list(flights.values())[0]
            
            if not flight_data:
                logging.info(f"No flight data found for {ident}")
                return None
            
            return {
                "airline": (flight_data.get("airline", {}) or {}).get("shortName", "Unknown Airline"),
                "identifier": flight_data.get("codeShare", {}).get("ident", ident),
                "link": url,
                "origin": {
                    "airport": flight_data.get("origin", {}).get("friendlyName", "Unknown Origin"),
                    "iata": flight_data.get("origin", {}).get("iata", "???"),
                    "departure_time": flight_data.get("takeoffTimes", {}).get("scheduled"),
                    "actual_departure_time": flight_data.get("takeoffTimes", {}).get("actual") or
                                             flight_data.get("takeoffTimes", {}).get("estimated"),
                    "coordinates": {
                        "lat": (flight_data.get("origin", {}).get("coord") or [0, 0])[1],
                        "lng": (flight_data.get("origin", {}).get("coord") or [0, 0])[0]
                    }
                },
                "destination": {
                    "airport": flight_data.get("destination", {}).get("friendlyName", "Unknown Destination"),
                    "iata": flight_data.get("destination", {}).get("iata", "???"),
                    "arrival_time": flight_data.get("landingTimes", {}).get("scheduled"),
                    "actual_arrival_time": flight_data.get("landingTimes", {}).get("actual") or
                                           flight_data.get("landingTimes", {}).get("estimated"),
                    "coordinates": {
                        "lat": (flight_data.get("destination", {}).get("coord") or [0, 0])[1],
                        "lng": (flight_data.get("destination", {}).get("coord") or [0, 0])[0]
                    }
                },
                "distance": {
                    "elapsed": flight_data.get("distance", {}).get("elapsed", 0),
                    "remaining": flight_data.get("distance", {}).get("remaining", 0)
                },
                "speed": flight_data.get("flightPlan", {}).get("speed", 0) if flight_data.get("flightPlan") else 0,
            }
    logging.error(f"Failed to fetch flight data from FlightAware: {flight_page.status_code}")
    return None
