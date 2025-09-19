// --- Map Initialization ---
const map = L.map('map').setView([40.7128, -74.0060], 13); // Default view (New York)
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

const etaBanner = document.getElementById('eta-banner');

// --- Custom Icons ---
const createIcon = (url) => L.icon({
    iconUrl: url,
    iconSize: [40, 40],       // Size of the icon
    iconAnchor: [20, 40],     // Point of the icon which will correspond to marker's location
    popupAnchor: [0, -40]     // Point from which the popup should open relative to the iconAnchor
});

const icons = {
    bus: createIcon('/images/bus.png'),
    home: createIcon('/images/home.png'),
    stop: createIcon('/images/busstop.png'),
    school: createIcon('/images/school.png')
};

// --- Markers ---
const markers = {
    bus: L.marker([0, 0], { icon: icons.bus, title: 'Bus' }).addTo(map),
    home: L.marker([0, 0], { icon: icons.home, title: 'Home' }).addTo(map),
    stop: L.marker([0, 0], { icon: icons.stop, title: 'Bus Stop' }).addTo(map),
    school: L.marker([0, 0], { icon: icons.school, title: 'School' }).addTo(map)
};

// --- Breadcrumb Trail ---
const busPath = [];
const breadcrumbTrail = L.polyline(busPath, { color: '#007bff', weight: 5, opacity: 0.7 }).addTo(map);

// --- MQTT and App Logic ---
let mqttClient;
let mqttConfig;

async function initializeApp() {
    etaBanner.textContent = 'Loading configuration...';
    try {
        const response = await fetch('/api/config');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        mqttConfig = await response.json();
        console.log('Configuration loaded:', mqttConfig);
        
        setupMqttClient();
    } catch (error) {
        console.error('Failed to load configuration:', error);
        etaBanner.textContent = 'Error loading config. Check console.';
        etaBanner.style.backgroundColor = '#ffcccc';
    }
}

function setupMqttClient() {
    mqttClient = new Paho.MQTT.Client(mqttConfig.mqtt_host, mqttConfig.mqtt_port, `bus-map-client-${Math.random()}`);
    mqttClient.onConnectionLost = onConnectionLost;
    mqttClient.onMessageArrived = onMessageArrived;
    connectToMqtt();
}

function connectToMqtt() {
    console.log(`Connecting to MQTT broker at ${mqttConfig.mqtt_host}:${mqttConfig.mqtt_port}...`);
    mqttClient.connect({
        userName: mqttConfig.mqtt_user,
        password: mqttConfig.mqtt_pass,
        onSuccess: onConnectSuccess,
        onFailure: onConnectFailure,
        useSSL: false // We are not using SSL on the local network
    });
}

function onConnectSuccess() {
    console.log('Connected to MQTT!');
    etaBanner.textContent = 'Connected. Waiting for data...';
    etaBanner.style.backgroundColor = '#ccffcc';
    mqttClient.subscribe(mqttConfig.mqtt_topic);
}

function onConnectFailure(message) {
    console.error('Connection failed:', message.errorMessage);
    etaBanner.textContent = 'MQTT Connection Failed. Retrying in 5s...';
    etaBanner.style.backgroundColor = '#ffcccc';
    setTimeout(connectToMqtt, 5000);
}

function onConnectionLost(responseObject) {
    if (responseObject.errorCode !== 0) {
        console.log('Connection lost:', responseObject.errorMessage);
        etaBanner.textContent = 'Connection Lost. Reconnecting...';
        etaBanner.style.backgroundColor = '#ffcccc';
        connectToMqtt();
    }
}

function onMessageArrived(message) {
    try {
        const data = JSON.parse(message.payloadString);
        console.log('Received data:', data);

        etaBanner.textContent = data.etaMsg || 'No ETA message';
        etaBanner.style.backgroundColor = 'rgba(255, 255, 255, 0.8)';

        const newLatLng = [data.bus_lat, data.bus_lon];

        // Update marker position
        markers.bus.setLatLng(newLatLng);

        // Update breadcrumb trail, avoiding duplicate points
        if (busPath.length === 0 || busPath[busPath.length - 1][0] !== newLatLng[0] || busPath[busPath.length - 1][1] !== newLatLng[1]) {
            if (data.bus_lat && data.bus_lon) { // Only add valid coordinates
                busPath.push(newLatLng);
                breadcrumbTrail.setLatLngs(busPath);
            }
        }
        markers.home.setLatLng([data.home_lat, data.home_lon]);
        markers.stop.setLatLng([data.stop_lat, data.stop_lon]);
        markers.school.setLatLng([data.school_lat, data.school_lon]);

        let bounds;
        const busLatLng = [data.bus_lat, data.bus_lon];
        const homeLatLng = [data.home_lat, data.home_lon];
        const stopLatLng = [data.stop_lat, data.stop_lon];
        const schoolLatLng = [data.school_lat, data.school_lon];

        if (data.bus_lat && data.home_lat) {
            if (data.etaMsg && data.etaMsg.toLowerCase().includes('approaching')) {
                bounds = L.latLngBounds([busLatLng, homeLatLng, stopLatLng, schoolLatLng]);
            } else {
                bounds = L.latLngBounds([busLatLng, homeLatLng, stopLatLng]);
            }
            map.fitBounds(bounds, { padding: [50, 50] });
        }
    } catch (e) {
        console.error('Error processing message:', e);
    }
}

// Start the application
initializeApp();
