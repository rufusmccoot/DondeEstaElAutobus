import os
import threading
import time
import traceback
import random
import json
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from selenium import webdriver
from flask import Flask, jsonify, send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS
from paho.mqtt.client import CallbackAPIVersion
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ANSI color codes
CYAN = "\033[96m"
RESET = "\033[0m"

# Load secrets from secrets.env
load_dotenv("secrets.env")

WTB_USER = os.getenv("wtb_userId")
WTB_PASS = os.getenv("wtb_password")
WTB_BUSID = os.getenv("wtb_busId")
WTB_CHDID = os.getenv("wtb_childId")
MQTT_SERVER = os.getenv("mqtt_server")
MQTT_PORT = int(os.getenv("mqtt_port", 1883))
MQTT_USER = os.getenv("mqtt_userId")
MQTT_PASS = os.getenv("mqtt_password")
MQTT_TOPIC = os.getenv("mqtt_topic")
MQTT_WS_PORT = int(os.getenv("mqtt_ws_port", 1884)) # Port for MQTT over WebSockets





def login(driver) -> str:
    """
    Use Selenium headless Chrome to log in, wait for reCAPTCHA, and extract sessionId from rider.php.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import re

    driver.get("https://wheresthebus.com/")
    time.sleep(2)
    driver.get("https://wheresthebus.com/au_login.php")
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.NAME, "email")))
    driver.find_element(By.NAME, "email").send_keys(WTB_USER)
    driver.find_element(By.NAME, "pw").send_keys(WTB_PASS)
    WebDriverWait(driver, 20).until(lambda d: d.find_element(By.ID, "token").get_attribute("value"))
    # Use a JS click to bypass the overlapping footer element
    commit_button = driver.find_element(By.NAME, "commit")
    driver.execute_script("arguments[0].click();", commit_button)
    time.sleep(3)
    if "rider.php" not in driver.current_url:
        return ""
    html = driver.page_source
    match = re.search(r'var s_app_id ?= ?[\"\"](.*?)["\"];', html)
    if match:
        return match.group(1)
    return ""

def get_rider_info_via_loadData(driver) -> dict:
    """
    Fetch rider info by calling the site's own loadData() JS function from within Selenium.
    """
    js = '''
        var callback = arguments[arguments.length - 1];
        try {
            if (typeof loadData === 'function') {
                var original_ajax = $.ajax;
                $.ajax = function(options) {
                    var original_success = options.success;
                    options.success = function(data) {
                        callback(JSON.stringify(data));
                        if (original_success) { original_success.apply(this, arguments); }
                    };
                    options.error = function(xhr, status, error) {
                        callback(JSON.stringify({error: "AJAX error", status: status, detail: error}));
                    };
                    return original_ajax.apply(this, arguments);
                };
                loadData();
                $.ajax = original_ajax;
            } else {
                callback(JSON.stringify({error: "loadData function not found"}));
            }
        } catch (err) {
            callback(JSON.stringify({error: "Exception calling loadData", raw: err.toString()}));
        }
    '''
    result = driver.execute_async_script(js)
    try:
        return json.loads(result)
    except Exception:
        return {"error": "Could not parse JSON", "raw": result}

def extract_mqtt_payload(full_payload: dict) -> dict:
    """
    Extract and rename fields for MQTT payload.
    """
    return {
        "home_lat": full_payload.get("homLat"),
        "home_lon": full_payload.get("homLon"),
        "school_lat": full_payload.get("schLat"),
        "school_lon": full_payload.get("schLon"),
        "bus_lat": full_payload.get("busLat"),
        "bus_lon": full_payload.get("busLon"),
        "stop_lat": full_payload.get("stpLat"),
        "stop_lon": full_payload.get("stpLon"),
        "dist": full_payload.get("dist"),
        "stsMsg": full_payload.get("stsMsg"),
        "etaMsg": full_payload.get("etaMsg"),
        "lst10Min": full_payload.get("lst10Min"),
        "childBuses": full_payload.get("childBuses"),
    }

def publish_to_mqtt(payload: dict):
    """
    Publish JSON payload to MQTT server.
    """
    client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2)
    if MQTT_USER and MQTT_PASS:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.connect(MQTT_SERVER, MQTT_PORT)
    client.publish(MQTT_TOPIC, json.dumps(payload), retain=True)
    client.disconnect()

def start_driver_and_login():
    options = Options()
    options.headless = True
#    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--headless=new")   
    # Suppress ChromeDriver logs
    options.add_argument('--log-level=3')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    session_id = login(driver)
    return driver, session_id

# --- Flask Web Server Setup ---
app = Flask(__name__, static_folder='frontend')
CORS(app)
socketio = SocketIO(app, async_mode='gevent')

# --- Polling Control ---
polling_enabled = threading.Event()
polling_enabled.set() # Start with polling enabled


# --- Socket.IO Event Handlers ---
@socketio.on('connect')
def handle_connect():
    # Send the initial status when a new client connects
    print(f"{CYAN}Client connected. Sending initial polling status.{RESET}")
    socketio.emit('status_update', {'polling_active': polling_enabled.is_set()})

@socketio.on('toggle_polling')
def handle_toggle_polling():
    """Toggle the polling loop on and off."""
    if polling_enabled.is_set():
        polling_enabled.clear() # Pause polling
        print(f"{CYAN}Polling paused by UI request.{RESET}")
    else:
        polling_enabled.set() # Resume polling
        print(f"{CYAN}Polling resumed by UI request.{RESET}")
    # Broadcast the new status to all clients
    socketio.emit('status_update', {'polling_active': polling_enabled.is_set()})

@socketio.on('request_status')
def handle_request_status():
    """Send the current polling status to the requesting client."""
    socketio.emit('status_update', {'polling_active': polling_enabled.is_set()})


@app.route('/api/config')
def get_config():
    """Provide MQTT config to the frontend (for internal HA use, if needed)."""
    return jsonify({
        'mqtt_host': MQTT_SERVER,
        'mqtt_port': MQTT_PORT, # Standard port, not WS
        'mqtt_user': MQTT_USER,
        'mqtt_pass': MQTT_PASS,
        'mqtt_topic': MQTT_TOPIC
    })

@app.route('/')
def serve_index():
    """Serve the main index.html file."""
    return send_from_directory('frontend', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    """Serve other static files from the frontend directory."""
    return send_from_directory('frontend', path)

def run_flask_app():
    # Running on 0.0.0.0 makes it accessible on the network
    # Use a different port like 5001 to avoid conflicts
    print("Starting Flask-SocketIO server...")
    socketio.run(app, host='0.0.0.0', port=5001, debug=False)

def polling_loop(driver):
    """The main polling loop to be run in a separate thread."""
    shutdown_time = None  # Initialize shutdown timer

    while True:
        polling_enabled.wait(timeout=5.0)
        if not polling_enabled.is_set():
            continue
        # If shutdown is scheduled, check if it's time to exit
        if shutdown_time and time.time() >= shutdown_time:
            print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Jittered exit timer complete. Exiting now.{RESET}")
            break
        try:
            print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - loadData(){RESET}")
            rider_info = get_rider_info_via_loadData(driver)

            if rider_info and 'payload' in rider_info and 'childBuses' in rider_info['payload']:
                payload = extract_mqtt_payload(rider_info.get("payload", {}))
                
                # 1. Publish to MQTT for Home Assistant's internal use
                publish_to_mqtt(payload)
                print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Pushed to MQTT{RESET}")

                # 2. Push data to all connected web clients via Socket.IO
                socketio.emit('bus_update', payload)
                print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Pushed to WebSockets{RESET}")

                # If bus is past stop and shutdown hasn't been scheduled yet, schedule it.
                if payload.get("dist") > 4.9 and payload.get("etaMsg") == "past stop" and not shutdown_time:
                    exit_delay = random.randint(60, 360)
                    shutdown_time = time.time() + exit_delay
                    print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Bus is past stop. Shutdown initiated. Will exit in approx {exit_delay // 60} minutes.{RESET}")
            else:
                print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - No valid payload found. Details: {rider_info}{RESET}")

        except Exception as e:
            print(f"An error occurred during polling: {e}")
            traceback.print_exc()
            print("Polling loop will continue, but may fail if browser state is corrupt.")

        sleep_time = 19 + random.uniform(-2, 2)
        time.sleep(sleep_time)

def main():
    # Start the Flask server in a daemon thread
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()
    print(f"{CYAN}Web server started at http://<your_ip>:5001{RESET}")

    driver = None
    try:
        driver, session_id = start_driver_and_login()
        if not session_id:
            print("Login failed. Exiting.")
            return

        # Start the polling loop in a separate thread
        polling_thread = threading.Thread(target=polling_loop, args=(driver,))
        polling_thread.daemon = True # This is the crucial change
        polling_thread.start()

        # Keep the main thread alive. The join() is removed, we'll just sleep.
        while polling_thread.is_alive():
            polling_thread.join(timeout=1.0) # Wait for 1s at a time

    except KeyboardInterrupt:
        print("\nCtrl+C detected. Shutting down.")
    finally:
        print("Cleaning up resources...")
        if driver:
            try:
                driver.quit()
            except Exception as e:
                print(f"Error quitting driver: {e}")

if __name__ == "__main__":
    main()
