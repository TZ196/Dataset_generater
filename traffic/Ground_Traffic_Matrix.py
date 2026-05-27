import os
import pandas as pd
import Temprol_module as tem
import Spatial_module as spm
import random
import math
import collections

GEANT_Normalized = [0.666375187, 0.618642091, 0.590977571, 0.563213085, 0.541584313, 0.533839914,
                    0.583266097, 0.667692083, 0.791995807, 0.888743851, 0.933041611, 0.981479064,
                    0.972636759, 0.990605207, 1.000000000, 0.950194854, 0.942922186, 0.881275688,
                    0.858416879, 0.834937010, 0.819007020, 0.810132998, 0.738902802, 0.691278814]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_ground_traffic(
    coordinate_path=None,
    output_dir=None,
    global_time=1000,
    offerload=0.1,
    band=1024,
):
    """
    生成地面站流量矩阵。

    参数：
        coordinate_path: coor_station.xlsx 路径 (默认 {BASE_DIR}/coor_station.xlsx)
        output_dir:      输出目录 (默认 {BASE_DIR}/ground_traffic)
        global_time:     仿真时间步数
        offerload:       流量负载因子
        band:            链路带宽 (Mbps)

    输出：
        {output_dir}/1000.xlsx — 地面站流量矩阵
    """
    if coordinate_path is None:
        coordinate_path = os.path.join(os.path.dirname(BASE_DIR), 'data', 'coor_station.xlsx')
    if output_dir is None:
        output_dir = os.path.join(BASE_DIR, 'ground_traffic')

    os.makedirs(output_dir, exist_ok=True)
    coordinate = pd.read_excel(coordinate_path, usecols=['lat', 'lon'])

    n_ter = coordinate.shape[0]
    demand = offerload * band * n_ter
    second = []

    for j in range(global_time):
        zone_stat_val_list = []
        zone_weight = tem.calculate_zone_weight(g_time=j, norm_traffic=GEANT_Normalized)
        zone_traffic = [i * demand for i in zone_weight]
        zone_density = spm.cal_stat_density(coordinate=coordinate)
        for i in range(24):
            zone_stat_value = spm.get_randomflow(total=zone_traffic[i], num=zone_density[i], time=j)
            zone_stat_value = collections.deque(zone_stat_value)
            zone_stat_val_list.append(zone_stat_value)

        destination = []
        traffic_value = []
        for i in range(coordinate.shape[0]):
            coor = coordinate.loc[i]
            lat, lon = tem.coord_trans(lat=coor['lat'], lon=coor['lon'])
            time_zone = math.floor(lon / 15)
            value = zone_stat_val_list[time_zone].popleft()
            # 论文公式(19): 每个站均匀随机选1个不同时区的目的地, F(i,j)=U(0.1,1)×f_i
            random.seed(j * 10000 + i)
            des_time_zone = time_zone
            while (des_time_zone == time_zone):
                des = random.randint(0, n_ter - 1)
                des_coor = coordinate.loc[des]
                lat, lon = tem.coord_trans(lat=des_coor['lat'], lon=des_coor['lon'])
                des_time_zone = math.floor(lon / 15)
            traffic = random.uniform(0.1, 1.0) * value
            destination.append("*")
            traffic_value.append("*")
            destination.append(des)
            traffic_value.append(traffic)
            destination.append("/")
            traffic_value.append("/")

        second.append(destination)
        second.append(traffic_value)

    import openpyxl
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for col_num, column in enumerate(second, start=1):
        for row_num, value in enumerate(column, start=1):
            sheet.cell(row=row_num, column=col_num, value=value)
    output_excel_path = os.path.join(output_dir, f'{global_time}.xlsx')
    workbook.save(output_excel_path)

    print(f"[地面流量] 完成! 输出: {output_dir}/{global_time}.xlsx")
    return os.path.join(output_dir, f'{global_time}.xlsx')


if __name__ == "__main__":
    generate_ground_traffic()
