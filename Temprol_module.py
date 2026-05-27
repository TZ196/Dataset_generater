import random
import math
import pandas as pd

GEANT_Normalized = [0.666375187, 0.618642091, 0.590977571, 0.563213085, 0.541584313, 0.533839914,
                    0.583266097, 0.667692083, 0.791995807, 0.888743851, 0.933041611, 0.981479064,
                    0.972636759, 0.990605207, 1.000000000, 0.950194854, 0.942922186, 0.881275688,
                    0.858416879, 0.834937010, 0.819007020, 0.810132998, 0.738902802, 0.691278814]

def coord_trans(lat, lon):

    latitude = abs(lat)
    if lon < 0:
        longitude = 360 + lon
    else:
        longitude = lon

    return latitude, longitude


def local_time(g_time, lon):

    loc_time = math.floor(g_time / 3600) + math.floor(lon / 15)
    if loc_time > 23:
        loc_time = loc_time - 24

    return loc_time


def Temproal_feature(g_time, coordinate, path):

    for i in range(g_time):
        norm_tmp = []
        for j in range(coordinate.shape[0]):
            coor = coordinate.loc[j]
            lat, lon = coord_trans(coor['lat'], coor['lon'])
            loc_time = local_time(i, lon=lon)
            normal = GEANT_Normalized[loc_time]
            norm_tmp.append(normal)

        df = pd.read_excel(path, header=None)
        new_column = pd.DataFrame(norm_tmp, columns=['New Column'])
        df = pd.concat([df, new_column], axis=1)
        df.to_excel(path, index=False, header=None)


def calculate_zone_weight(g_time, norm_traffic):

    g_time = g_time
    zone_weight = []
    time_zone = math.floor(g_time / 3600)   # UTC 标准时区的时间
    zone_weight.append(norm_traffic[time_zone] / sum(norm_traffic))
    for i in range(23):
        next_zone = time_zone + i + 1
        if next_zone > 23:
            next_zone = next_zone - 24
        next_weight = norm_traffic[next_zone] / sum(norm_traffic)
        zone_weight.append(next_weight)

    return zone_weight