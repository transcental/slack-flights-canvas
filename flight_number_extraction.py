from re import compile
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

flight_number_pattern = compile(
    r"\b[A-Za-z]{2,3}[\s-]?\d{1,4}\b|\b\d{3,4}\b"
)

# Pattern to match flight number with optional date/time specification
# Format: FLIGHT123@2026-01-03 or FLIGHT123@2026-01-03T14:30 or FLIGHT123@2026-01-03T14:30:00
flight_with_datetime_pattern = compile(
    r"(\b[A-Za-z]{2,3}[\s-]?\d{1,4}\b|\b\d{3,4}\b)@(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?)"
)


@dataclass
class FlightSpec:
    """Represents a flight number with optional date/time specification."""
    flight_number: str
    date_time: Optional[datetime] = None

    def __str__(self):
        if self.date_time:
            return f"{self.flight_number}@{self.date_time.strftime('%Y-%m-%dT%H:%M:%S')}"
        return self.flight_number


def extract_flight_numbers(text: str) -> list[str]:
    """
    Extracts flight numbers from the given text.
    :param text: The text to extract flight numbers from.
    :return: A list of flight numbers found in the text.
    """
    return flight_number_pattern.findall(text)


def extract_flight_specs(text: str) -> list[FlightSpec]:
    """
    Extracts flight specifications (flight number with optional date/time) from the given text.
    :param text: The text to extract flight specifications from.
    :return: A list of FlightSpec objects.
    """
    flight_specs = []
    
    # First, try to find flights with date/time specifications
    datetime_matches = flight_with_datetime_pattern.findall(text)
    matched_positions = []
    
    for match in flight_with_datetime_pattern.finditer(text):
        matched_positions.append((match.start(), match.end()))
        flight_number = match.group(1).replace(" ", "").replace("-", "")
        datetime_str = match.group(2)
        
        # Parse the datetime string
        parsed_datetime = None
        try:
            if 'T' in datetime_str:
                # Try full datetime format
                if datetime_str.count(':') == 2:
                    parsed_datetime = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%S")
                else:
                    parsed_datetime = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M")
            else:
                # Date only - use midnight
                parsed_datetime = datetime.strptime(datetime_str, "%Y-%m-%d")
        except ValueError:
            # If parsing fails, treat it as a regular flight number
            pass
        
        flight_specs.append(FlightSpec(flight_number=flight_number, date_time=parsed_datetime))
    
    # Then find regular flight numbers not already matched
    for match in flight_number_pattern.finditer(text):
        # Check if this match overlaps with a datetime match
        is_overlapping = False
        for start, end in matched_positions:
            if match.start() >= start and match.end() <= end:
                is_overlapping = True
                break
        
        if not is_overlapping:
            flight_number = match.group(0).replace(" ", "").replace("-", "")
            flight_specs.append(FlightSpec(flight_number=flight_number, date_time=None))
    
    return flight_specs
