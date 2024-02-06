# See https://geopandas.org/en/stable/gallery/create_geopandas_from_pandas.html

import geopandas
from geodatasets import get_path
import pandas as pd
import matplotlib.pyplot as plt


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

    ax.set_aspect("equal")
    plt.show()


# Durango, Mexico
latitude = 24.83333
longitude = -104.83333

plot_location(longitude, latitude)
