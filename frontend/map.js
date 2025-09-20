// --- Map Initialization ---
const map = L.map('map').setView([40.7128, -74.0060], 13); // Default view
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

const etaBanner = document.getElementById('eta-banner');
const toggleBtn = document.getElementById('toggle-polling-btn');

// --- Custom Icons ---
const createIcon = (url) => L.icon({
    iconUrl: url,
    iconSize: [50, 50],
    iconAnchor: [25, 25],
    popupAnchor: [0, -25]
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

// --- Socket.IO Connection ---

// Connect to the Socket.IO server. 
// It will automatically connect to the host that served the page.
// For Ingress, the path needs to be specified correctly.
const socketPath = window.location.pathname.replace(/\/$/, '') + '/socket.io';
console.log(`Connecting to Socket.IO with path: ${socketPath}`);

const socket = io(window.location.origin, {
    path: socketPath
});

socket.on('connect', () => {
    console.log('Socket.IO connected successfully!');
    etaBanner.textContent = 'Connected. Waiting for data...';
    // When we connect (or reconnect), ask the server for the current polling status
    socket.emit('request_status');
});

// --- UI Event Handlers ---
function updatePollingButton(isActive) {
    if (isActive) {
        toggleBtn.textContent = 'Polling Active';
        toggleBtn.className = 'active';
    } else {
        toggleBtn.textContent = 'Polling Paused';
        toggleBtn.className = 'paused';
    }
}

toggleBtn.addEventListener('click', () => {
    console.log('Toggle button clicked.');
    socket.emit('toggle_polling');
});

// Listen for status updates from the server
socket.on('status_update', (data) => {
    console.log('Received status update:', data);
    updatePollingButton(data.polling_active);
});

socket.on('disconnect', () => {
    console.log('Socket.IO disconnected.');
    etaBanner.textContent = 'Connection Lost. Retrying...';
});

socket.on('connect_error', (err) => {
    console.error('Socket.IO connection error:', err);
    etaBanner.textContent = 'Connection Error. Check console.';
});

// Listen for our custom 'bus_update' event
socket.on('bus_update', (data) => {
    try {
        console.log('Received bus update:', data);

        etaBanner.textContent = data.etaMsg || 'No ETA message';
        etaBanner.style.backgroundColor = 'rgba(40, 40, 40, 0.85)'; // Reset to dark

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

        // Auto-zoom logic
        let bounds = L.latLngBounds([newLatLng, [data.home_lat, data.home_lon], [data.stop_lat, data.stop_lon]]);
        if (data.etaMsg && data.etaMsg.toLowerCase().includes('approaching')) {
            bounds.extend([data.school_lat, data.school_lon]);
        }
        map.fitBounds(bounds, { padding: [50, 50] });

    } catch (e) {
        console.error('Error processing message:', e);
    }
});
