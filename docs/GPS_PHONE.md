# Getting GPS Coordinates from Your Smartphone

Solar Eclipse Workbench can use your smartphone's GPS to automatically capture
your exact observation location. This guide covers every scenario including
**remote sites with no WiFi**.

---

## How It Works

When you click **📱 Get GPS from Phone** in the wizard (or run
`python scripts/get_gps_location.py --web`), the application:

1. Generates a temporary self-signed HTTPS certificate.
2. Starts a small web server on your laptop (default port 8765).
3. Displays the server URL — open it on your phone's browser.
4. The browser page asks for location permission and reads the phone GPS.
5. The coordinates are submitted to the server and filled into the wizard.
6. The server shuts down automatically.

No app installation is required on the phone. Any modern browser (Chrome,
Firefox, Safari) works.

---

## Scenarios

### Scenario A — WiFi available at the observation site

Both your phone and laptop are connected to the same WiFi network. This is the
simplest case.

1. Connect both devices to the same WiFi network.
2. Click **📱 Get GPS from Phone** (or run the script).
3. Scan the QR code, or open the URL shown (e.g. `https://192.168.1.42:8765/?k=Xy3...`) on your phone.
   Type the whole URL: the `?k=...` part is a random access key, and without it the page answers
   "Forbidden", so nobody else on the network can send a false location.
4. Accept the certificate warning (see [below](#accepting-the-certificate-warning)).
5. Tap **📍 Get My Location** and allow location access when prompted.
6. The page submits the coordinates and you can close the browser.

---

### Scenario B — No WiFi (use phone as a hotspot) ★ most common at eclipse sites ★

You can connect your laptop to the internet (or just to a local network) through
your phone's mobile hotspot. The GPS page and location submission all happen
**locally** — no internet access is needed after the server starts.

#### Android

1. Open **Settings** → **Network & internet** (or **Connections**) →
   **Hotspot & tethering** → **Wi-Fi hotspot**.
2. Tap **Use Wi-Fi Hotspot** to enable it. Note the network name (SSID) and
   password shown, or set them yourself under **Hotspot name / password**.
3. On your **laptop**, open the WiFi menu and connect to that hotspot network.
4. Start the GPS capture in Solar Eclipse Workbench.
5. Open the URL shown on your **phone's own browser** (Chrome or Firefox
   recommended). The phone is both the hotspot provider *and* the GPS client —
   this works fine.
6. Tap **📍 Get My Location** and allow location access.

> **Tip (Android)**  
> Android's hotspot IP address is usually `192.168.43.1` and it assigns the
> laptop an address like `192.168.43.xxx`. The URL shown by the workbench will
> reflect the correct laptop IP automatically.

> **Battery note**  
> Using the hotspot and GPS simultaneously drains the battery faster. Plug the
> phone in or bring a power bank.

#### iPhone / iPad

1. Open **Settings** → **Personal Hotspot**.
2. Toggle **Allow Others to Join** on. Note the WiFi password.
3. Optionally edit the WiFi password by tapping it.
4. On your **laptop**, connect to the hotspot network (named after your iPhone,
   e.g. *John's iPhone*).
5. Start the GPS capture in Solar Eclipse Workbench.
6. Open the URL shown on your **iPhone's own browser** (Safari recommended).
   iPhone assigns itself the address `172.20.10.1`; the workbench detects the
   correct laptop IP automatically.
7. Tap **📍 Get My Location** and allow location access.

> **Tip (iPhone)**  
> iOS requires the app requesting location to have permission. Safari will ask
> the first time. If the prompt never appears, go to **Settings** → **Privacy &
> Security** → **Location Services** → **Safari** and set it to *While Using*.

> **Tip (iPhone)**  
> The Personal Hotspot screen must remain visible on the iPhone while other
> devices are connecting; it may time out otherwise.

---

## Accepting the Certificate Warning

Because the server uses a **self-signed certificate** (generated fresh each
time, stored only in RAM), every browser will show a security warning. This is
expected and safe — the certificate only proves HTTPS encryption, not a
publicly trusted identity.

### Chrome / Android WebView
1. Tap **Advanced**.
2. Tap **Proceed to \<IP address\> (unsafe)**.

### Safari (iOS / macOS)
1. Tap / click **Show Details**.
2. Tap / click **Visit this website**.
3. Confirm by tapping **Visit Website** in the alert that appears.

### Firefox
1. Click **Advanced…**
2. Click **Accept the Risk and Continue**.

Once accepted, the warning is gone for this session. The next time you run the
GPS capture, a new certificate is generated and you will need to accept again.

---

## Manual Coordinate Entry

If automatic GPS does not work (the browser reports "Position unavailable" —
common on desktops and some Android devices without mobile data), scroll down to
the **Manual / form entry** section on the GPS page and type in the coordinates
directly, then click **✔ Send location**.

You can look up your coordinates beforehand with:
- [Google Maps](https://maps.google.com) — right-click any point on the map,
  the first item in the menu is the coordinates.
- [what3words](https://what3words.com) or any other mapping service.

---

## Standalone Script

The GPS capture can also be run independently, without opening the full wizard:

```bash
# Activate the project environment first:
source .venv/bin/activate    # Linux / macOS
.venv\Scripts\activate       # Windows

python scripts/get_gps_location.py --web
```

The script prints the server URL, waits for coordinates, prints a formatted fix,
and exits.

```
GPS capture server running (HTTPS).

From your PHONE (same WiFi or phone hotspot):
    https://10.33.178.15:8765/?k=q3Vn8xT0aLk2

  Certificate warning: tap 'Advanced' → 'Proceed' (Chrome)
                    or 'Show Details' → 'Visit this website' (Safari)

From this LAPTOP (to test):
    https://localhost:8765/?k=q3Vn8xT0aLk2

  → Location received from 10.33.178.15: lat=50.830412, lon=4.863891

  Lat: +50.830412°  (50°49'49.48"N)
  Lon: +4.863891°  (4°51'50.01"E)
  Alt: 38.0 m   ...

Ready to paste into Solar Eclipse Workbench:
  Latitude  : 50.830412
  Longitude : 4.863891
  Altitude  : 38.0 m
```

Optional arguments:

| Flag | Default | Description |
|------|---------|-------------|
| `--web-port PORT` | `8765` | TCP port for the HTTPS server |
| `--timeout SECONDS` | `300` | How long to wait for coordinates |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Browser cannot reach the URL | Devices on different networks | Check both are on the same WiFi / hotspot |
| "Position unavailable" | No GPS hardware or permission denied | Use manual entry or move outdoors |
| Certificate warning never goes away | Old browser that caches rejection | Clear browser data or try a different browser |
| Server prints `Could not generate HTTPS certificate` | `openssl` not installed | `sudo apt install openssl` (Linux) / `brew install openssl` (macOS) — falls back to HTTP, geolocation may not work on mobile |
| Location has very low accuracy | Phone geolocation uses WiFi / cell towers, not GPS | Move outdoors; wait 30 s for a proper GPS fix |

---

## Privacy

All communication is local to your network. No data is sent to the internet.
The self-signed certificate is generated fresh each time and discarded when
the server stops.
