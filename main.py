import os
import time
import traceback
import random
import json
import re
import requests
import paho.mqtt.client as mqtt
import shutil
from dotenv import load_dotenv
from selenium import webdriver
from paho.mqtt.client import CallbackAPIVersion
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Constants and Globals ---
CYAN = "\033[96m"
RESET = "\033[0m"

# --- Configuration Loading ---
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

# --- Core Functions ---

def publish_to_mqtt(payload)\
    
    """Publishes a JSON payload to the configured MQTT topic."""
    client = mqtt.Client(CallbackAPIVersion.VERSION2)
    if MQTT_USER and MQTT_PASS:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    try:
        client.connect(MQTT_SERVER, MQTT_PORT, 60)
        client.publish(MQTT_TOPIC, json.dumps(payload), retain=True)
        client.disconnect()
    except Exception as e:
        print(f"Failed to publish to MQTT: {e}")

def extract_mqtt_payload(payload_data):
    """Extracts relevant fields from the API payload for MQTT."""
    return {
        "bus_lat": payload_data.get("busLat"),
        "bus_lon": payload_data.get("busLon"),
        "etaMsg": payload_data.get("etaMsg"),
        "dist": payload_data.get("dist"),
        "school_lat": payload_data.get("schLat"),
        "school_lon": payload_data.get("schLon"),
        "home_lat": payload_data.get("homLat"),
        "home_lon": payload_data.get("homLon"),
        "stop_lat": payload_data.get("stpLat"),
        "stop_lon": payload_data.get("stpLon"),
    }

def polling_loop(session_id):
    """The main polling loop to fetch data via API and publish to MQTT."""
    api_url = "https://mdt.veonow.com/sh_05/wtbparentapp/api/v2/getRiderInfo"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
        'Referer': 'https://wheresthebus.com/',
        'Origin': 'https://wheresthebus.com',
        'Content-Type': 'application/json',
    }
    post_payload = {
        "sessionId": session_id,
        "bid": WTB_BUSID,
        "chdId": int(WTB_CHDID)
    }

    shutdown_time = None
    while True:
        if shutdown_time and time.time() >= shutdown_time:
            print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Jittered exit timer complete. Exiting now.{RESET}")
            break
        try:
            print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Polling API for data...{RESET}")
            response = requests.post(api_url, headers=headers, json=post_payload)
            response.raise_for_status()
            rider_info = response.json()

            if rider_info and 'payload' in rider_info:
                mqtt_payload = extract_mqtt_payload(rider_info['payload'])
                publish_to_mqtt(mqtt_payload)
                print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Pushed to MQTT.{RESET}")

                bus_dist = mqtt_payload.get("dist")
                if bus_dist is not None and bus_dist > 1.9 and mqtt_payload.get("etaMsg") == "past stop" and not shutdown_time:
                    exit_delay = random.randint(30, 180)
                    shutdown_time = time.time() + exit_delay
                    print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - Bus is past stop. Scheduling shutdown in ~{exit_delay // 60} minutes.{RESET}")
            else:
                print(f"{CYAN}{time.strftime('%Y-%m-%d %H:%M:%S')} - 'payload' key not found in API response.{RESET}")

        except requests.exceptions.RequestException as e:
            print(f"An error occurred during API request: {e}")
        except Exception as e:
            print(f"An error occurred during polling: {e}")
            traceback.print_exc()

        sleep_time = 19 + random.uniform(-2, 2)
        time.sleep(sleep_time)

def main():
    """Main function to log in via Selenium, then run the API polling loop."""
    driver = None
    try:
        print("Starting Selenium driver for login...")
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        print("Chrome driver initialized.")
        
        driver.get("https://wheresthebus.com/au_login.php")
        
        email_field = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "email")))
        email_field.send_keys(WTB_USER)
        driver.find_element(By.ID, "pw").send_keys(WTB_PASS)
        
        time.sleep(1) # Pause to allow page to settle
        
        print("Clicking login button via JavaScript to avoid interception...")
        login_button = driver.find_element(By.NAME, "commit")
        driver.execute_script("arguments[0].click();", login_button)
        
        WebDriverWait(driver, 15).until(EC.url_contains("rider.php"))
        print("Selenium login successful.")

        page_source = driver.page_source
        match = re.search(r'var s_app_id ?= ?["\'](.*?)["\'];', page_source)
        if not match:
            print("Could not find s_app_id on page. Exiting.")
            return
        session_id = match.group(1)
        print(f"Extracted session ID (s_app_id): {session_id}")

        print("Shutting down Selenium.")
        driver.quit()
        driver = None

        polling_loop(session_id)

    except Exception as e:
        print(f"An error occurred during the main process: {e}")
        traceback.print_exc()

    finally:
        print("Cleaning up resources...")
        if driver:
            driver.quit()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Shutting down.")
