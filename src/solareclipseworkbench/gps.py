# Add the GPS, check the port, 
# GPSD_SOCKET="/usr/local/var/gpsd.sock" /usr/local/Cellar/gpsd/3.25/sbin/gpsdctl add /dev/ttys010
from gpsdclient import GPSDClient

# get your data as json strings:
# with GPSDClient(host="127.0.0.1") as client:
#     for result in client.json_stream():
#         print(result)

# or as python dicts (optionally convert time information to `datetime` objects)
with GPSDClient(host="127.0.0.1") as client:
    # for result in client.json_stream():
    #     print(result)
    for result in client.dict_stream(convert_datetime=True, filter=["TPV"]):
        print("Latitude: %s" % result.get("lat", "n/a"))
        print("Longitude: %s" % result.get("lon", "n/a"))

# you can optionally filter by report class
with GPSDClient() as client:
    for result in client.dict_stream(filter=["TPV", "SKY"]):
        print(result)