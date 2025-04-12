# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import signal
import sys
from types import FrameType

from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

from geopy.geocoders import Nominatim

from google.cloud import firestore


from utils.logging import logger

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes


# Initialize Firestore client
db = firestore.Client()

# Initialize Geolocator
geolocator = Nominatim(user_agent="xrp_geocoder")

def geocode_ip(ip_address):
    """Geocode an IP address into a location."""
    try:
        # Placeholder geocoding logic for IP (replace with actual API or method as needed)
        location = geolocator.geocode(ip_address)
        if location:
            return {
                "latitude": location.latitude,
                "longitude": location.longitude,
                "city": location.raw.get("address", {}).get("city", "Unknown"),
                "state": location.raw.get("address", {}).get("state", "Unknown")
            }
    except Exception as e:
        print(f"Geocoding failed for IP {ip_address}: {e}")
    return {"latitude": None, "longitude": None, "city": "Unknown", "state": "Unknown"}

@app.route('/data', methods=['POST'])
def create_data_entry():
    # Get JSON data from the request
    data = request.json

    # Check if 'robot_id' is present in the request body
    if 'XRPID' not in data:
        return jsonify({'error': 'invalid usage'}), 400

    # Extract fields from the JSON data
    xrp_id = data.get('XRPID')
    platform = data.get('platform')
    ble = data.get('BLE')

    # Get client IP address and user agent information
    #ip_address = request.remote_addr
    # Extract the client's IP address from the X-Forwarded-For header
    x_forwarded_for = request.headers.get('X-Forwarded-For', '')
    ip_address = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.remote_addr

    user_agent = request.headers.get('User-Agent')

    # Create a dictionary to store the data
    entry = {
        'xrp_id': xrp_id,
        'platform': platform,
        'ble': ble,
        'timestamp': datetime.utcnow(),
        'ip_address': ip_address,
        'user_agent': user_agent
    }

    # Add the entry to Firestore
    db.collection('data_entries').add(entry)

    return jsonify({"message": "Data entry created successfully"}), 201

@app.route("/")
def hello() -> str:
    # Use basic logging with custom fields
    logger.info(logField="custom-entry", arbitraryField="custom-entry")

    # https://cloud.google.com/run/docs/logging#correlate-logs
    logger.info("Child logger with trace Id.")

    return "version 1!"

@app.route("/api/getData", methods=["GET"])
def get_data():
    try:
        # Get date range from query parameters
        start_date = request.args.get("start", (datetime.now() - timedelta(days=7)).isoformat())
        end_date = request.args.get("end", datetime.now().isoformat())

        # Convert to timestamps
        start_timestamp = datetime.fromisoformat(start_date)
        end_timestamp = datetime.fromisoformat(end_date)

        # Query Firestore for data within the date range
        docs = db.collection('data_entries')
                  .where("timestamp", ">=", start_timestamp)
                  .where("timestamp", "<=", end_timestamp)
                  .stream()

        # Parse documents and geocode missing locations
        data = []
        for doc in docs:
            entry = doc.to_dict()
            if not (entry.get("latitude") and entry.get("longitude")):
                geocoded = geocode_ip(entry.get("ip_address", ""))
                entry.update(geocoded)

                # Optionally update Firestore with geocoded data
                db.collection('data_entries').document(doc.id).update(geocoded)

            data.append(entry)

        return jsonify({"status": "success", "data": data})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def shutdown_handler(signal_int: int, frame: FrameType) -> None:
    logger.info(f"Caught Signal {signal.strsignal(signal_int)}")

    from utils.logging import flush

    flush()

    # Safely exit program
    sys.exit(0)


if __name__ == "__main__":
    # Running application locally, outside of a Google Cloud Environment

    # handles Ctrl-C termination
    signal.signal(signal.SIGINT, shutdown_handler)

    app.run(host="localhost", port=8080, debug=True)
else:
    # handles Cloud Run container termination
    signal.signal(signal.SIGTERM, shutdown_handler)
