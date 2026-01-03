import os
import threading
import time
from json import dumps
from os import environ
from queue import Queue
from uuid import uuid4
from datetime import datetime

from cachetools import TTLCache, cached
from dotenv import load_dotenv
from flask import Flask, request, Response

from scrape_flightaware import get_flight_ident, get_flight_data
from flight_number_extraction import extract_flight_specs, FlightSpec

load_dotenv()

app = Flask(__name__)

secret_tokens = environ.get("SECRET_TOKENS", "").split(",")

if not secret_tokens or not all(secret_tokens):
    raise ValueError("SECRET_TOKENS environment variable must be set with at least one token.")


def validate_token(token):
    if not token or token not in secret_tokens:
        return False
    return True

FLIGHT_DATA_TTL = 60 * 5
STALE_DATA_TTL = 60 * 15

ident_cache = TTLCache(maxsize=2048, ttl=60 * 60 * 24 * 7)
ident_cache_lock = threading.Lock()

flight_data_cache = TTLCache(maxsize=1024, ttl=STALE_DATA_TTL)
flight_data_cache_lock = threading.Lock()

task_queue = Queue()
results = {}


@cached(ident_cache, lock=ident_cache_lock)
def cached_get_flight_ident(flight_number):
    return get_flight_ident(flight_number)


def _background_refresh_flight_data(ident):
    """
    Worker function to fetch fresh data and update the cache in the background.
    This runs in a separate thread and does not block the user's request.
    """
    try:
        fresh_data = get_flight_data(ident)
        if fresh_data:
            with flight_data_cache_lock:
                flight_data_cache[ident] = (fresh_data, time.time())
    except Exception as e:
        # Log the error but don't crash the thread. The old data will persist.
        print(f"Background refresh for ident {ident} failed: {e}")


def get_full_flight_data(flight_spec: FlightSpec):
    """
    Get flight data for a given flight specification (number + optional date/time).
    
    :param flight_spec: FlightSpec containing flight number and optional date/time.
    :return: Flight data dictionary or None.
    """
    ident = cached_get_flight_ident(flight_spec.flight_number)
    if not ident:
        return None

    # For date-specific requests, don't use cache
    if flight_spec.date_time:
        return get_flight_data(ident, flight_spec.date_time)

    with flight_data_cache_lock:
        cached_item = flight_data_cache.get(ident)

    now = time.time()

    # Data is older than 15 mins
    if not cached_item or (now - cached_item[1]) > STALE_DATA_TTL:
        fresh_data = get_flight_data(ident, flight_spec.date_time)
        if fresh_data:
            with flight_data_cache_lock:
                flight_data_cache[ident] = (fresh_data, now)
        return fresh_data

    cached_data, fetch_time = cached_item
    age = now - fetch_time

    # Data is stale (> 5 mins old but < 15 mins old)
    if age > FLIGHT_DATA_TTL:
        # Start a new thread so the current request is not blocked
        threading.Thread(
            target=_background_refresh_flight_data,
            args=(ident,),
            daemon=True
        ).start()

    # Return cached data
    return cached_data


def worker():
    while True:
        request_id, original_flight_spec_str, flight_spec = task_queue.get()
        try:
            result = get_full_flight_data(flight_spec)
            if not result:
                result = {"error": "Flight data not found or could not be scraped."}

            result['original_flight_number'] = original_flight_spec_str
            result['scraped_at'] = time.time()

            if request_id in results:
                results[request_id].put(result)
        except Exception as e:
            print(f"Worker error for flight {original_flight_spec_str}: {e}")
            result_payload = {
                "status": "error",
                "result": {"error": f"An unexpected error occurred: {str(e)}"}
            }
            if request_id in results:
                results[request_id].put({
                    "original_flight_number": original_flight_spec_str,
                    "scraped_at": time.time(),
                    **result_payload
                })
        finally:
            task_queue.task_done()


worker_threads = []


def start_worker_threads():
    num_threads = int(os.environ.get("NUM_THREADS", os.cpu_count()))
    for _ in range(num_threads):
        threading.Thread(target=worker, daemon=True).start()


@app.route("/api/scrape/<flight_numbers>")
def scrape(flight_numbers):
    if not validate_token(request.args.get("token")):
        return "Invalid token", 403

    request_id = str(uuid4())
    flight_list = []
    for number in flight_numbers.split(","):
        original_number = number.strip()
        # Parse flight spec (flight number with optional date/time)
        flight_specs = extract_flight_specs(original_number)
        if flight_specs and len(flight_specs) > 0:
            # Use the first flight spec found
            flight_spec = flight_specs[0]
            flight_list.append((original_number, flight_spec))

    results[request_id] = Queue()

    for original, spec in flight_list:
        task_queue.put((request_id, original, spec))

    def stream():
        items_processed = 0
        total_items = len(flight_list)
        try:
            while items_processed < total_items:
                result_data = results[request_id].get(timeout=480)
                yield dumps({
                    "type": "flight_data",
                    "request_id": request_id,
                    "flight_number": result_data["original_flight_number"],
                    "status": "completed",
                    "result": result_data
                }) + "\n"
                items_processed += 1
        except Exception as e:
            print(f"Error while streaming results: {e}")
        finally:
            yield dumps({
                "type": "end",
                "request_id": request_id,
                "status": "completed"
            }) + "\n"
            if request_id in results:
                del results[request_id]

    return Response(stream(), mimetype='application/json')


if __name__ == "__main__":
    start_worker_threads()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), threaded=True)
