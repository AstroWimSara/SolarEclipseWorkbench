# See https://geopandas.org/en/stable/gallery/create_geopandas_from_pandas.html

import geopandas
from geodatasets import get_path
import pandas as pd
import matplotlib.pyplot as plt


def plot_current_location():
    """ Plots the current location on the world map."""

    longitude, latitude = get_current_location()
    plot_location(longitude, latitude)


def get_current_location() -> (float, float):
    """ Returns the longitude and latitude of the current location.

    Both coordinates are expressed in degrees.

    Returns: (longitude, latitude) of the current location [degrees].
    """

    pass


def plot_location(longitude: float, latitude: float):
    """ Plot the given location on the world map.

    Args:
        - longitude: Longitude of the location [degrees]
        - latitude: Latitude of the location [degrees]
    """

    df = pd.DataFrame(
        {
            "Latitude": [latitude],
            "Longitude": [longitude],
        }
    )

    gdf = geopandas.GeoDataFrame(df, geometry=geopandas.points_from_xy(df.Longitude, df.Latitude), crs="EPSG:4326")

    world = geopandas.read_file(get_path("naturalearth.land"))
    # Crop -> min longitude, min latitude, max longitude, max latitude
    ax = world.clip([-180, -90, 180, 90]).plot(color="white", edgecolor="black")

    gdf.plot(ax=ax, color="red")
    plt.show()


# Durango, Mexico
latitude = 24.83333
longitude = -104.83333

plot_location(longitude, latitude)
