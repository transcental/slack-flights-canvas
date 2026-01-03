import logging
from datetime import datetime
from enum import Enum
from json import loads, JSONDecodeError
from typing import Optional

from requests import get
from slack_bolt import App

from find_json import find_json, find_json_url
from flight_number_extraction import extract_flight_numbers
from info_message_format import FLIGHT_INFO_FORMAT_VERSION, FLIGHT_INFO_TITLE, format_flight_info_message, \
    combine_flight_info_messages
from parse_canvas import CanvasLine, parse_canvas
from scrape_flightaware import get_flight_ident, get_flight_data


def clean_canvas(content: str) -> str:
    return (
        content.replace('\xa0', ' ')  # Replace non-breaking spaces with regular spaces
        .replace('\n\n', '\n')  # Remove extra newlines
        .strip()
    )


class CanvasEditResult(Enum):
    CURRENTLY_TRACKING = 1  # Keep sending edits on an interval
    NOT_TRACKING = 2  # Stop sending edits, no tracking


locks = []


class CanvasEditor:
    def __init__(self, app: App, file_id: str, token: str):
        if file_id in locks:
            logging.warning(f"Canvas {file_id} is already being edited, skipping")
            return
        locks.append(file_id)
        self.app = app
        self.file_id = file_id
        self.token = token
        self.canvas_content: Optional[list[CanvasLine]] = None
        self.bot_mention_line: Optional[CanvasLine] = None
        self.tracking_last_updated_line: Optional[CanvasLine] = None
        self.config = {}  # Canvas-specific configuration
        self.map_data = {}
        self.initial_map_update = True
        self.load_canvas(file_id)
        if not self.canvas_content:
            logging.error(f"Failed to load canvas content for file {file_id}")
            return
        if not self.find_bot_line():
            logging.error(f"Bot mention line not found in canvas {file_id}")
            return
        self.load_config()
        if self.map_enabled():
            self.add_map_data()
        else:
            logging.info("Map is not enabled, skipping map data initialization")
        self.add_flight_info()

        locks.remove(file_id)  # Release the lock after editing is done

    def get_canvas_url(self, file_id: str) -> Optional[str]:
        file_info = self.app.client.files_info(file=file_id)
        if not file_info['ok']:
            logging.error(f"Failed to load canvas {file_id}: {file_info['error']}")
            return None
        if 'file' not in file_info:
            logging.error(f"File missing for {file_id}")
            return None
        file = file_info['file']
        if file['mimetype'] != 'application/vnd.slack-docs':
            logging.warning(f"File {file_id} is not a canvas: {file['mimetype']}")
            return None
        if 'url_private_download' not in file:
            logging.error(f"File {file_id} does not have a URL")
            return None
        return file['url_private_download']

    def update_line(self, content: str, line_id: str, replace: bool):
        """
        Updates the line in the canvas with the given content.
        :param content: The markdown content to update the line with.
        :param replace: Whether to replace the existing line or insert a new one below it.
        """
        self.app.client.canvases_edit(
            canvas_id=self.file_id,
            changes=[
                {
                    "operation": "replace" if replace else "insert_after",
                    "section_id": line_id,
                    "document_content": {
                        "type": "markdown",
                        "markdown": content
                    }
                }
            ]
        )

    def load_canvas(self, file_id: str):
        file_url = self.get_canvas_url(file_id)
        if not file_url:
            logging.error(f"Could not load canvas {file_id}")
            return
        headers = {
            "Authorization": f"Bearer {self.token}"
        }
        response = get(file_url, headers=headers)
        if response.status_code != 200:
            logging.error(f"Failed to download canvas {file_id}: {response.status_code}")
            return
        content = response.text
        cleaned_content = clean_canvas(content)
        if not cleaned_content:
            logging.warning(f"Canvas {file_id} is empty")
            return
        self.canvas_content = parse_canvas(cleaned_content)

    def find_bot_line(self) -> bool:
        """
        Makes sure the bot is mentioned somewhere in the canvas.
        """
        if not self.canvas_content:
            logging.error("Canvas content is not loaded")
            return False
        bot_id_request = self.app.client.auth_test()
        if not bot_id_request['ok']:
            logging.error(f"Failed to get bot ID: {bot_id_request['error']}")
            return False
        if 'user_id' not in bot_id_request:
            logging.error("Bot ID not found in auth_test response")
            return False
        bot_id = bot_id_request['user_id']
        for line in self.canvas_content:
            if f"@{bot_id}" in line.text:
                self.bot_mention_line = line
                return True
        logging.warning("Bot is not mentioned in the canvas")
        return False

    def load_config(self):
        if not self.canvas_content:
            logging.error("Canvas content is not loaded")
            return
        if not self.bot_mention_line:
            logging.error("Bot mention line is not set")
            return
        for line in self.canvas_content:
            if line == self.bot_mention_line:
                config_json_text = find_json(line.text)
                if not config_json_text:
                    # Check for a JSON URL instead
                    config_json_url = find_json_url(line.text)
                    if config_json_url:
                        logging.info(f"Found JSON URL in bot mention line: {config_json_url}")
                        try:
                            response = get(config_json_url)
                            response.raise_for_status()
                            config_json_text = response.text
                        except Exception as e:
                            logging.error(f"Failed to fetch JSON from URL {config_json_url}: {e}")
                            return
                    else:
                        logging.warning("No JSON configuration found in the bot mention line")
                        return
                # Slack uses typographical quotes, so we need to replace them with regular quotes
                config_json_text = config_json_text.replace('“', '"').replace('”', '"')
                try:
                    self.config = loads(config_json_text)
                except JSONDecodeError as e:
                    logging.error(f"Failed to parse JSON from bot mention line: {e}")
                    return
        if not self.config:
            logging.warning("No configuration found in the canvas")

    def map_enabled(self) -> bool:
        """
        Checks if the map is enabled in the canvas configuration.
        :return: True if the map is enabled, False otherwise.
        """
        if not self.config:
            logging.error("Configuration is not loaded")
            return False
        if 'tracking' not in self.config:
            logging.error("Tracking configuration is missing")
            return False
        if not self.config['tracking'].get('enabled', False):
            logging.warning("Tracking is not enabled in the configuration")
            return False
        if 'map' not in self.config['tracking']:
            logging.error("Map configuration is missing in the tracking settings")
            return False
        if not self.config['tracking']['map'].get('enabled', False):
            logging.warning("Map is not enabled in the tracking configuration")
            return False
        return True

    def find_tracking_last_updated(self) -> Optional[datetime]:
        if not self.canvas_content:
            logging.error("Canvas content is not loaded")
            return None
        if not self.tracking_last_updated_line:
            for line in self.canvas_content:
                if "Flights Canvas tracking:" in line.text:
                    self.tracking_last_updated_line = line
                    break
        if not self.tracking_last_updated_line:
            logging.warning("Tracking last updated line not found in the canvas")
            return None
        line = self.tracking_last_updated_line
        if "Not tracking" in line.text:
            return None
        date_str = line.text.split("Flights Canvas tracking:")[-1].strip()
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError as e:
            logging.error(f"Failed to parse date from canvas line: {e}")
            return None

        logging.warning("No tracking last updated found in the canvas")
        return None

    def track_interval(self) -> bool:
        """
        Determines whether tracking data should be updated on an interval.
        :return: Whether to track data on an interval.
        """
        if not self.config:
            logging.error("Configuration is not loaded")
            return False
        if 'tracking' not in self.config:
            logging.error("Tracking configuration is missing")
            return False
        if not self.config['tracking'].get('enabled', False):
            logging.warning("Tracking is not enabled in the configuration")
            return False
        if 'arrival_dates' not in self.config['tracking']:
            logging.error("Arrival dates are not configured for tracking")
            return False
        today = datetime.now()
        arrival_dates = self.config['tracking']['arrival_dates']
        parsed_arrival_dates = []
        for date_str in arrival_dates:
            try:
                parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
                parsed_arrival_dates.append(parsed_date)
            except ValueError as e:
                logging.error(f"Failed to parse arrival date '{date_str}': {e}")
                continue
        for date in parsed_arrival_dates:
            if abs((date - today).total_seconds()) // (60 * 60 * 24 * 1) == 0 or (  # 1 hour of difference is acceptable
                    abs((date - today).total_seconds() / (60 * 60 * 1)) <= 1 and
                    (date - today).total_seconds() // (60 * 60 * 24 * 1) in [-1, 0, 1]
            ):
                return True
        return False

    def track_now(self) -> bool:
        """
        Determines whether tracking data should be updated immediately.
        :return: Whether to track data immediately.
        """
        if not self.track_interval():
            return False
        last_updated = self.find_tracking_last_updated()
        now = datetime.now()
        if not last_updated or (now - last_updated).total_seconds() / (60 * 1) >= 2:
            return True
        return False

    def set_tracking_last_updated(self):
        """
        Updates the tracking last updated line in the canvas with the current date.
        """
        if not self.canvas_content:
            logging.error("Canvas content is not loaded")
            return
        text = ""
        if self.track_interval():
            text = f"Flights Canvas tracking: {datetime.now().strftime('%Y-%m-%d')}"
        else:
            if self.find_tracking_last_updated() is None:
                return  # Already set to not tracking (or missing)
            text = "Flights Canvas tracking: Not tracking"
        # Always search for the tracking line before updating
        tracking_line = None
        for line in self.canvas_content:
            if "Flights Canvas tracking:" in line.text:
                tracking_line = line
                break
        if not tracking_line:
            logging.info("Tracking last updated line not found, adding it to the canvas")
            self.update_line(
                content=text,
                line_id=self.bot_mention_line.id,
                replace=False
            )
            self.tracking_last_updated_line = CanvasLine(self.bot_mention_line.element)
        else:
            logging.info("Updating tracking last updated line in the canvas")
            self.update_line(
                content=text,
                line_id=tracking_line.id,
                replace=True
            )
            tracking_line.text = text
            self.tracking_last_updated_line = tracking_line

    def add_map_data(self):
        """
        Adds configured points of interest (POIs) and themes to the map data.
        This does not verify the integrity of the configuration, it assumes that the configuration is valid.
        """
        if not self.map_enabled():
            logging.warning("Map is not enabled, skipping POI & theme addition")
            return
        if not self.config or 'tracking' not in self.config or 'map' not in self.config['tracking']:
            logging.error("Map configuration is missing in the tracking settings")
            return
        self.map_data["pois"] = self.config['tracking']['map'].get('pois', [])
        self.map_data["themes"] = self.config['tracking']['map'].get('themes', [])
        self.map_data["tracking"] = {
            "arrivalDates": self.config['tracking'].get('arrival_dates', []),
            "currentlyTracking": self.track_now()
        }
        self.map_data["file_id"] = self.file_id
        logging.info("Map data initialized with configured POIs and themes")


    def update_map_data(self, flight_info):
        """
        Updates the map data with the flight information.
        :param flight_info: The flight information to update the map with.
        """
        if not self.map_enabled():
            logging.warning("Map is not enabled, skipping map data update")
            return
        if not flight_info:
            logging.error("Flight info is empty, cannot update map data")
            return
        flight_number = flight_info.get('identifier', None)
        if not flight_number:
            logging.error("Flight number is missing in flight info, cannot update map data")
            return
        origin_airport = {
            "name": flight_info.get('origin', {}).get('airport', 'Unknown Origin'),
            "lat": flight_info.get('origin', {}).get('coordinates', {}).get('lat', 0.0),
            "lon": flight_info.get('origin', {}).get('coordinates', {}).get('lon', 0.0)
        }
        destination_airport = {
            "name": flight_info.get('destination', {}).get('airport', 'Unknown Destination'),
            "lat": flight_info.get('destination', {}).get('coordinates', {}).get('lat', 0.0),
            "lon": flight_info.get('destination', {}).get('coordinates', {}).get('lon', 0.0)
        }
        if origin_airport not in self.map_data.get('airports', []):
            self.map_data.setdefault('airports', []).append(origin_airport)
        if destination_airport not in self.map_data.get('airports', []):
            self.map_data.setdefault('airports', []).append(destination_airport)
        flights_list = self.map_data.setdefault('flights', [])
        # Check if this flight already exists in the list (by identifier)
        existing_flight = next((f for f in flights_list if f.get('identifier') == flight_number), None)
        flight_entry = {
            "identifier": flight_number,
            "origin": origin_airport,
            "destination": destination_airport,
            "elapsedDistance": flight_info.get('distance', {}).get('elapsed', 0),
            "remainingDistance": flight_info.get('distance', {}).get('remaining', 0),
            "speed": flight_info.get('speed', 0),
            "lastUpdatedAt": datetime.now().timestamp() * 1000  # Convert to milliseconds
        }
        if existing_flight:
            flights_list.remove(existing_flight)
        flights_list.append(flight_entry)
        logging.info(f"Map data updated for flight {flight_number}")

    def get_map_data(self) -> dict:
        """
        Returns the map data for the canvas.
        :return: A dictionary containing the map data.
        """
        if not self.map_enabled():
            logging.warning("Map is not enabled, returning empty map data")
            return {}
        return self.map_data

    def add_flight_info(self):
        """
        Adds flight information to the canvas when it is not already present.
        """
        if not self.canvas_content:
            logging.error("Canvas content is not loaded")
            return

        i = 0
        while i < len(self.canvas_content):
            line = self.canvas_content[i]
            i += 1
            if line in [self.bot_mention_line, self.tracking_last_updated_line]:
                continue
            if FLIGHT_INFO_TITLE in line.text:
                continue
            flight_numbers = extract_flight_numbers(line.text)
            if not flight_numbers:
                logging.info(f"No flight numbers found in line: {line.text}")
                continue
            replace_existing = False
            next_line = None
            if i < len(self.canvas_content):
                next_line = self.canvas_content[i]
                if FLIGHT_INFO_TITLE in next_line.text:
                    if FLIGHT_INFO_FORMAT_VERSION in next_line.text and not (self.track_now() or (self.map_enabled() and self.initial_map_update)):
                        logging.info("Flight info already present")
                        continue
                    else:
                        logging.info("Replacing existing flight info in the canvas")
                        replace_existing = True
            info_messages = {}  # Flight number: info message
            for flight in flight_numbers:
                flight_ident = get_flight_ident(flight)
                flight_info = get_flight_data(flight_ident)
                if not flight_info:
                    logging.warning(
                        f"Failed to scrape flight info for {flight}")  # Not an error because flight numbers may be inaccurate
                    continue
                if self.map_enabled():
                    self.update_map_data(flight_info)
                flight_number = flight_info.get('identifier', flight)
                if flight_number in info_messages:
                    logging.info(f"Flight info for {flight_number} already exists, skipping")
                    continue
                info_message = format_flight_info_message(flight_info, self.track_now())
                info_messages[flight_number] = info_message
            flight_message = combine_flight_info_messages(info_messages.values())
            if replace_existing:
                self.update_line(
                    content=flight_message,
                    line_id=next_line.id,
                    replace=True
                )
            else:
                self.update_line(
                    content=flight_message,
                    line_id=line.id,
                    replace=False
                )
        if not self.initial_map_update:
            self.initial_map_update = False

    def get_result(self):
        """
        Returns the result of the canvas edit operation.
        :return: CanvasEditResult indicating whether tracking is currently active or not.
        """
        if self.track_interval():
            return CanvasEditResult.CURRENTLY_TRACKING
        else:
            return CanvasEditResult.NOT_TRACKING
