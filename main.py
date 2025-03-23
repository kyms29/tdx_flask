import os
import random

from flask import Flask, request, jsonify, send_from_directory, url_for
import time
import requests
import sys

from flask_talisman import Talisman
from scipy.spatial import KDTree
import math
from apscheduler.schedulers.background import BackgroundScheduler

sys.stdout.reconfigure(encoding="utf-8")

cityList = ["Taipei", "NewTaipei", "Taoyuan"]

CLIENT_ID = "f61434-61c72fa6-5118-433c"
CLIENT_SECRET = "5883cba9-2468-4477-bb2a-8cd3389291e2"

TOKEN_URL ="https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
STATION_API_URL = "https://tdx.transportdata.tw/api/basic/v2/Bike/Station/City/{City}"

AVAILABLE_API_URL = "https://tdx.transportdata.tw/api/basic/v2/Bike/Availability/City/{City}"
IMAGE_FOLDER = "./static/image"
bike_stations = []

app = Flask(__name__)
scheduler = BackgroundScheduler()
# Get TDX Token
def get_access_token():
    try:
        payload = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "client_credentials",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        response = requests.post(TOKEN_URL, data=payload, headers=headers)

        if response.status_code == 200:
            token_data = response.json()
            return token_data["access_token"]
        else:
            print(f"Failed to get token: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error while fetching token: {e}")
        return None


def fetch_station_data(token, city):
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        station_response = requests.get(STATION_API_URL.format(City=city), headers=headers)

        if station_response.status_code == 200:
            stations = station_response.json()
            print(f"GET {city} stations size = {len(stations)}")
            return stations
        else:
            print(f"Unable to fetch station for {city}")
            return None
    except Exception as e:
        print(f"Fetch station for {city} error : {e}")
        return None


def fetch_availability_data(token, city):
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        availability_response = requests.get(AVAILABLE_API_URL.format(City=city), headers=headers)

        if availability_response.status_code == 200:
            availabilities = availability_response.json()
            print(f"GET {city} availabilities size = {len(availabilities)}")
            return availabilities
        else:
            print(f"Unable to fetch availability for {city}")
            return None
    except Exception as e:
        print(f"Fetch availability for {city} error : {e}")
        return None


def fetch_all():
    # get all city's data
    start_time = time.time()

    # modify this part for
    # bike_stations.clear()
    new_bike_stations = []

    token = get_access_token()

    for city in cityList:
        stations = fetch_station_data(token, city)
        time.sleep(0.5)
        availabilities = fetch_availability_data(token, city)
        time.sleep(0.5)

        availability_dict = {a["StationUID"]: a for a in availabilities}

        for station in stations:
            uid = station["StationUID"]
            new_bike_stations.append({
                "station_uid": uid,
                "station_name": station["StationName"]["Zh_tw"],
                "station_address": station.get("StationAddress", {}).get("Zh_tw"),
                "lat": station["StationPosition"]["PositionLat"],
                "lng": station["StationPosition"]["PositionLon"],
                "update_time": station["UpdateTime"],
                "available_bikes": availability_dict.get(uid, {}).get("AvailableRentBikesDetail", {}).get(
                    "GeneralBikes", 0),
                "available_e_bikes": availability_dict.get(uid, {}).get("AvailableRentBikesDetail", {}).get(
                    "ElectricBikes", 0),
                "available_return": availability_dict.get(uid, {}).get("AvailableReturnBikes", 0),

            })
    bike_stations.clear()
    bike_stations.extend(new_bike_stations)
    end_time = time.time()
    print(f"fetch all station 執行時間: {round(end_time - start_time, 4)} 秒")

def schedule_jobs():
    if not scheduler.get_job('fetch_all_job'):
        scheduler.add_job(fetch_all, 'interval', minutes=1, id='fetch_all_job')
        print("Schedular add job")
        scheduler.start()

def build_kdtree(stations):
    points = [(s["lat"], s["lng"]) for s in stations]
    kdtree = KDTree(points)
    return kdtree, stations


def find_nearby_stations(user_lat, user_lng, kdtree, stations, radius_km=1.0):
    radius_deg = radius_km / 111  # 1° ≈ 111 km
    nearby_indices = kdtree.query_ball_point((user_lat, user_lng), radius_deg)

    nearby_stations = []
    for idx in nearby_indices:
        station = stations[idx]
        station["distance_km"] = round(haversine(user_lat, user_lng, station["lat"], station["lng"]), 2)
        nearby_stations.append(station)

    return sorted(nearby_stations, key=lambda x: x["distance_km"])


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) * math.sin(dlat / 2) + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)) * math.sin(dlon / 2) * math.sin(dlon / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

@app.route('/nearby_stations', methods=['GET'])
def nearby_stations():
    if not bike_stations:
        return jsonify({"error":"No station data available"}),404

    kdtree, stations = build_kdtree(bike_stations)

    user_lat = request.args.get('lat',type=float)
    user_lng = request.args.get('lng',type=float)
    user_range = request.args.get('range',type=float)

    if user_lat is None or user_lng is None or user_range is None:
        return jsonify({"error": "Missing or invalid parameters. Please provide lat, lng, and range as numbers."}), 400

    print(f"Got request, user_lat = {user_lat}, user_lng = {user_lng}, user_range = {user_range}")

    start_time = time.time()
    result = find_nearby_stations(user_lat, user_lng, kdtree, stations, radius_km=user_range)
    # base_url = request.host_url

    base_url = request.host_url
    image_files = sorted(os.listdir(IMAGE_FOLDER))
    num_images = len(image_files)

    for i, station in enumerate(result):
        if "image_url" not in station:
            image_index = i % num_images
            station["image_url"] = f"{base_url}static/image/{image_files[image_index]}"

    end_time = time.time()
    print(f"Spend time : {round(end_time - start_time, 4)} 秒")
    print(f"Result size： {len(result)}")

    return jsonify(result),200

@app.route('/all_stations', methods=['GET'])
def all_stations():
    if not bike_stations:
        return jsonify({"error":"No station data available"}),404
    else:
        base_url = request.host_url
        for station in bike_stations:
            if "image_url" not in station:
                image_files = os.listdir(IMAGE_FOLDER)
                random_image = random.choice(image_files)
                station["image_url"] = f"{base_url}static/image/{random_image}"
        return jsonify(bike_stations),200

if __name__ == '__main__':
    fetch_all()
    schedule_jobs()
    app.run(host='0.0.0.0',debug=False,ssl_context=('server.crt', 'server.key'))
