# Slack Flights Canvas

Ping your Slack bot in a canvas with flight numbers, and it will return information about each flight.

## Installation

Set environment variables or create a `.env` file with the following content:

```dotenv
SLACK_SIGNING_SECRET=""
SLACK_BOT_TOKEN=""
```

Build the online map files:

```shell
npm install
npm run build
```

Set the default map file ID (from Slack):

```dotenv
DEFAULT_FILE_ID=""
```

You can optionally set the `PORT` variable to change the port on which the server runs (default is 5000).

```shell
pip install uv
uv run main.py
```

## Usage

### Flight Number Formats

The bot recognizes flight numbers in your canvas and can fetch information about them. You can specify flights in two ways:

1. **Basic flight number**: Simply mention the flight number (e.g., `AA123`, `BA456`, `UA789`)
2. **Flight with specific date/time**: Add `@YYYY-MM-DD` or `@YYYY-MM-DDTHH:MM` after the flight number to get information about a specific flight instance

**Examples:**
- `AA123` - Gets the current/most recent flight AA123
- `AA123@2026-01-03` - Gets flight AA123 scheduled for January 3, 2026
- `BA456@2026-01-04T14:30` - Gets flight BA456 scheduled for January 4, 2026 at 14:30
- `UA789@2026-01-05T09:15:00` - Gets flight UA789 scheduled for January 5, 2026 at 09:15:00

This is useful when tracking specific flight instances, as flight numbers are typically reused daily.

## Configuration

On the same line that you mention the bot, add a JSON object or a URL (ending in `.json`).

See [shipwrecked_config.json](shipwrecked_config.json) for an example configuration made for Hack Club's Shipwrecked
event.

If you've enabled the map feature, visit `/map/<canvas_file_id>` to see the map. Prepend `/api` for a programmatic
interface. Set `DEFAULT_FILE_ID` to redirect `/` to a specific map file.

## Scraping API

If you don't want or need the Slack features, the `scrape_api.py` file adds an API to scrape flight information from
FlightAware. You can run it with:

```shell
pip install uv
uv run scrape_api.py
```

Be sure to set the `SECRET_TOKENS` environment variable to a comma-separated list of tokens that will be used to
authenticate requests.

Requests to the API should be made to `/api/scrape/<flight_numbers>`, where `<flight_numbers>` is a comma-separated
list of flight numbers. The API will return a streaming response with flight information in JSON format.

**API Examples:**
- `/api/scrape/AA123?token=YOUR_TOKEN` - Get current flight AA123
- `/api/scrape/AA123@2026-01-03?token=YOUR_TOKEN` - Get flight AA123 on January 3, 2026
- `/api/scrape/AA123@2026-01-03T14:30,BA456@2026-01-04?token=YOUR_TOKEN` - Get multiple flights with specific dates
