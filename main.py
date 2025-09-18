import os
import time
import random
import json
import traceback

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from selenium import webdriver
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
    driver.find_element(By.NAME, "commit").click()
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

def main():
    driver, session_id = start_driver_and_login()
    if not session_id:
        print("Login failed.")
        return

    shutdown_time = None  # Initialize shutdown timer

    try:
        while True:
            # If shutdown is scheduled, check if it's time to exit
            if shutdown_time and time.time() >= shutdown_time:
                print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Jittered exit timer complete. Exiting now.{RESET}")
                break
            try:
                print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - loadData(){RESET}")
                rider_info = get_rider_info_via_loadData(driver)

                if rider_info and 'payload' in rider_info and 'childBuses' in rider_info['payload']:
                    print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Result: 'childBuses': {rider_info['payload']['childBuses']}{RESET}")
                    payload = extract_mqtt_payload(rider_info.get("payload", {}))
                    publish_to_mqtt(payload)

                    # If bus is past stop and shutdown hasn't been scheduled yet, schedule it.
                    if payload.get("dist") > 4.9 and payload.get("etaMsg") == "past stop" and not shutdown_time:
                        exit_delay = random.randint(60, 360)
                        shutdown_time = time.time() + exit_delay
                        print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Bus is past stop. Shutdown initiated. Will exit in approx {exit_delay // 60} minutes.{RESET}")
                else:
                    print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - No valid payload found. Details: {rider_info}{RESET}")

            except Exception as e:
                print(f"An error occurred: {e}")
                traceback.print_exc()
                print("Attempting to restart browser and re-login...")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver, session_id = start_driver_and_login()
                if not driver:
                    print("Failed to restart and login. Exiting.")
                    return

            sleep_time = 19 + random.uniform(-2, 2)
            time.sleep(sleep_time)

    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
