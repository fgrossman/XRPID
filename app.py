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

from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

import requests

from google.cloud import firestore


from utils.logging import logger

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Initialize Firestore client
db = firestore.Client()

IPINFO_TOKEN = '4d022234dbb4fc'

def geocode_ip(ip_address):
    # First, check if we already have geocoded data for this IP address
    try:
        # Query Firestore for existing entries with this IP address that have latitude data
        existing_docs = db.collection('data_entries').where("ip_address", "==", ip_address).where("latitude", "!=", None).limit(1).stream()
        
        for doc in existing_docs:
            entry = doc.to_dict()
            if entry.get("latitude") and entry.get("longitude"):
                # Return existing geocoded data
                return {
                    "latitude": entry.get("latitude"),
                    "longitude": entry.get("longitude"),
                    "city": entry.get("city", "Unknown"),
                    "state": entry.get("state", "Unknown")
                }
    except Exception as e:
        print(f"Failed to query existing geocoded data for {ip_address}: {e}")

    # If no existing data found, call ipinfo API
    try:
        response = requests.get(f'https://ipinfo.io/{ip_address}?token={IPINFO_TOKEN}')
        if response.status_code == 200:
            data = response.json()
            if 'loc' in data:
                latitude, longitude = map(float, data['loc'].split(','))
                return {
                    "latitude": latitude,
                    "longitude": longitude,
                    "city": data.get('city', 'Unknown'),
                    "state": data.get('region', 'Unknown')
                }
    except Exception as e:
        print(f"Failed to geocode {ip_address}: {e}")

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

    geocoded = geocode_ip(entry.get("ip_address", ""))
    entry.update(geocoded)

    # Add the entry to Firestore
    db.collection('data_entries').add(entry)

    return jsonify({"message": "Data entry created successfully"}), 201

@app.route("/")
def hello() -> str:
    # Use basic logging with custom fields
    logger.info(logField="custom-entry", arbitraryField="custom-entry")

    # https://cloud.google.com/run/docs/logging#correlate-logs
    logger.info("Child logger with trace Id.")

    return "version 2.1!"

@app.route("/dashboard")
def index():
    # Serve the HTML file
    return render_template("index.html")

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
        docs = db.collection('data_entries').where("timestamp", ">=", start_timestamp).where("timestamp", "<=", end_timestamp).stream()

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
