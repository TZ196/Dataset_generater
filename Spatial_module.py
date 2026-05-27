import numpy as np
import pandas as pd
import math
import Temprol_module as tem
import random


def cal_stat_density(coordinate):

    num_station_zone = [0] * 24 
    for i in range(coordinate.shape[0]):
        coor = coordinate.loc[i]
        lat, lon = tem.coord_trans(coor['lat'], coor['lon'])
        time_zone = math.floor(lon / 15)
        num_station_zone[time_zone] = num_station_zone[time_zone] + 1

    return num_station_zone


def get_randomflow(total, num, time):

    random.seed(time)
    random_numbers = [random.uniform(0, 1) for _ in range(num)] 
    ratio = total / sum(random_numbers)
    random_numbers = [number * ratio for number in random_numbers]

    return random_numbers

