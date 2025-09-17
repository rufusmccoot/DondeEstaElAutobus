# DondeEstaElAutobus

Python script to log in to wheresthebus.com, poll for bus/child info, and publish results to an MQTT server.

## Setup
1. Create and activate a Python virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
2. Install requirements:
   ```
   pip install -r requirements.txt
   ```
   - For headless login automation, Chrome must be installed on your system.
   - Selenium and webdriver-manager will auto-download the correct driver.

3. Fill in your secrets in `secrets.env`.
4. Run the script:
   ```
   python main.py
   ```

## Notes
- This project is intended to be run via Task Scheduler with a batch file.
- `secrets.env` and `venv/` are excluded from git.
