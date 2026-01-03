from re import compile
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

flight_number_pattern = compile(
    r"\b[A-Za-z]{2,3}[\s-]?\d{1,4}\b|\b\d{3,4}\b"
)

# Pattern to match flight number with optional date/time specification using @ symbol
# Format: FLIGHT123@2026-01-03 or FLIGHT123@2026-01-03T14:30 or FLIGHT123@2026-01-03T14:30:00
flight_with_datetime_pattern = compile(
    r"(\b[A-Za-z]{2,3}[\s-]?\d{1,4}\b|\b\d{3,4}\b)@(\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?)"
)

# Pattern to match flight number followed by date and optional time (natural format)
# Format: BA698 03/01/26 14:50 or BA698 03/01/2026 or BA698 3/1/26
flight_with_natural_datetime_pattern = compile(
    r"(\b[A-Za-z]{2,3}[\s-]?\d{1,4})\s+(\d{1,2}/\d{1,2}/\d{2,4})(?:\s+(\d{1,2}:\d{2}))?(?!\d)"
)

# Pattern to match flight number followed by time only (no date)
# Format: BA698 14:50
flight_with_time_only_pattern = compile(
    r"(\b[A-Za-z]{2,3}[\s-]?\d{1,4})\s+(\d{1,2}:\d{2})(?!\d|/)"
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
    Supports multiple formats:
    - FLIGHT123 (just flight number)
    - FLIGHT123@2026-01-03 (with @ and ISO date)
    - FLIGHT123@2026-01-03T14:30 (with @ and ISO datetime)
    - BA698 03/01/26 14:50 (natural format with date and time)
    - BA698 03/01/26 (natural format with date only)
    - BA698 14:50 (time only, uses today's date)
    
    :param text: The text to extract flight specifications from.
    :return: A list of FlightSpec objects.
    """
    flight_specs = []
    matched_positions = []
    
    # First, try to find flights with @ date/time specifications
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
    
    # Second, try to find flights with natural date/time format (e.g., "BA698 03/01/26 14:50")
    for match in flight_with_natural_datetime_pattern.finditer(text):
        # Check if this match overlaps with a @ datetime match
        is_overlapping = False
        for start, end in matched_positions:
            if (match.start() >= start and match.start() < end) or (match.end() > start and match.end() <= end):
                is_overlapping = True
                break
        
        if not is_overlapping:
            matched_positions.append((match.start(), match.end()))
            flight_number = match.group(1).replace(" ", "").replace("-", "")
            date_str = match.group(2)  # e.g., "03/01/26" or "03/01/2026"
            time_str = match.group(3)  # e.g., "14:50" or None
            
            # Parse the date string
            parsed_datetime = None
            try:
                # Try different date formats
                date_parts = date_str.split('/')
                if len(date_parts) == 3:
                    month, day, year = date_parts
                    # Handle 2-digit or 4-digit year
                    if len(year) == 2:
                        # Assume 20xx for years 00-99
                        year = f"20{year}"
                    
                    if time_str:
                        # Parse with time
                        full_datetime_str = f"{year}-{month}-{day} {time_str}"
                        parsed_datetime = datetime.strptime(full_datetime_str, "%Y-%m-%d %H:%M")
                    else:
                        # Parse date only
                        full_date_str = f"{year}-{month}-{day}"
                        parsed_datetime = datetime.strptime(full_date_str, "%Y-%m-%d")
            except (ValueError, IndexError) as e:
                # If parsing fails, skip this match
                pass
            
            if parsed_datetime:
                flight_specs.append(FlightSpec(flight_number=flight_number, date_time=parsed_datetime))
    
    # Third, try to find flights with time only (no date, uses today's date)
    for match in flight_with_time_only_pattern.finditer(text):
        # Check if this match overlaps with any previous match
        is_overlapping = False
        for start, end in matched_positions:
            if (match.start() >= start and match.start() < end) or (match.end() > start and match.end() <= end):
                is_overlapping = True
                break
        
        if not is_overlapping:
            matched_positions.append((match.start(), match.end()))
            flight_number = match.group(1).replace(" ", "").replace("-", "")
            time_str = match.group(2)  # e.g., "14:50"
            
            # Use today's date with the specified time
            parsed_datetime = None
            try:
                today = datetime.now().date()
                time_parts = time_str.split(':')
                if len(time_parts) == 2:
                    hour, minute = int(time_parts[0]), int(time_parts[1])
                    parsed_datetime = datetime(today.year, today.month, today.day, hour, minute)
            except (ValueError, IndexError):
                # If parsing fails, skip this match
                pass
            
            if parsed_datetime:
                flight_specs.append(FlightSpec(flight_number=flight_number, date_time=parsed_datetime))
    
    # Finally, find regular flight numbers not already matched
    for match in flight_number_pattern.finditer(text):
        # Check if this match overlaps with any datetime match
        is_overlapping = False
        for start, end in matched_positions:
            if match.start() >= start and match.end() <= end:
                is_overlapping = True
                break
        
        if not is_overlapping:
            flight_number = match.group(0).replace(" ", "").replace("-", "")
            flight_specs.append(FlightSpec(flight_number=flight_number, date_time=None))
    
    return flight_specs
