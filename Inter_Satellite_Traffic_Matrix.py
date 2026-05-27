"""
星间流量矩阵生成
=================
将地面站级流量（Stage 2 输出）映射为卫星级流量矩阵。
依赖 Stage 1 的星地可见性 CSV 和 Stage 2 的地面流量 1000.xlsx。
"""

import os
import pandas as pd
import Ground_To_Satellite_module as gsm
import openpyxl

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def generate_inter_satellite_traffic(
    vis_dir=None,
    ground_traffic_path=None,
    sat_names_path=None,
    output_dir=None,
    global_time=1000,
    n_ground_stations=910,
    file_prefix="ground",
):
    """
    生成星间流量矩阵。

    参数：
        vis_dir:             可见性 CSV 目录 (默认 {BASE_DIR}/visibility_output)
        ground_traffic_path: 地面流量 xlsx 路径 (默认 {BASE_DIR}/ground_traffic/1000.xlsx)
        sat_names_path:      卫星名称 xlsx 路径 (默认 {BASE_DIR}/visibility_output/satellite_names.xlsx)
        output_dir:          输出目录 (默认 {BASE_DIR}/inter_satellite_traffic)
        global_time:         时间步数
        n_ground_stations:   地面站数量
        file_prefix:         可见性文件名前缀

    输出：
        {output_dir}/{1..global_time}.xlsx — 每个时间步的星间流量矩阵
    """
    if vis_dir is None:
        vis_dir = os.path.join(BASE_DIR, 'visibility_output')
    if ground_traffic_path is None:
        ground_traffic_path = os.path.join(BASE_DIR, 'ground_traffic', '1000.xlsx')
    if sat_names_path is None:
        sat_names_path = os.path.join(BASE_DIR, 'visibility_output', 'satellite_names.xlsx')
    if output_dir is None:
        output_dir = os.path.join(BASE_DIR, 'inter_satellite_traffic')

    os.makedirs(output_dir, exist_ok=True)

    # ── 1. 加载星地可见性数据 ──
    first_csv = os.path.join(vis_dir, f"{file_prefix}_1sawable.csv")
    if not os.path.exists(first_csv):
        # Also try without underscore before 'sawable'
        first_csv = os.path.join(vis_dir, f"{file_prefix}_1_sawable.csv")

    sat_ground_data = pd.read_csv(first_csv)
    loaded_count = 1

    for i in range(2, n_ground_stations + 1):
        # Try both naming patterns
        path_a = os.path.join(vis_dir, f"{file_prefix}_{i}sawable.csv")
        path_b = os.path.join(vis_dir, f"{file_prefix}_{i}_sawable.csv")
        if os.path.exists(path_a):
            path = path_a
        elif os.path.exists(path_b):
            path = path_b
        else:
            print(f"  [跳过] 地面站 {i}: 未找到可见性文件")
            continue
        try:
            data = pd.read_csv(path)
            sat_ground_data = pd.concat([sat_ground_data, data], ignore_index=True)
            loaded_count += 1
        except Exception:
            print(f"  [警告] 地面站 {i}: 读取失败")

    print(f"[星间流量] 已加载 {loaded_count}/{n_ground_stations} 个地面站的可见性数据")

    # ── 2. 加载地面流量矩阵 ──
    ground_matrix = pd.read_excel(ground_traffic_path, header=None)
    print(f"[星间流量] 地面流量矩阵: {ground_matrix.shape}")

    # ── 3. 加载卫星名称列表 ──
    sate_num = pd.read_excel(sat_names_path, header=None)
    sate_ref = {}
    for i in range(len(sate_num)):
        sate_ref[sate_num.loc[i][0]] = i
    print(f"[星间流量] 卫星数量: {len(sate_ref)}")

    # ── 4. 逐时间步生成星间流量矩阵 ──
    sat_matrix_all = []

    for j in range(global_time):
        dst_ground_count = 0
        print(f"  时间步 {j+1}/{global_time}")
        ground_sat = gsm.cal_ground_sat(g_time=j, data=sat_ground_data)
        sat_matrix = [[0] * len(sate_ref) for _ in range(len(sate_ref))]

        for i in range(n_ground_stations):
            dst_ground = []
            dst_ground_value = []
            src_ground = 'target' + str(i + 1)
            dst_column = int(2 * j)

            try:
                if (ground_matrix.loc[dst_ground_count][dst_column] == '*'):
                    dst_ground_count = dst_ground_count + 1
                    while True:
                        cell_val = ground_matrix.loc[dst_ground_count][dst_column]
                        if cell_val == '/':
                            dst_ground_count = dst_ground_count + 1
                            break
                        dst_ground.append(
                            'target' + str(int(ground_matrix.loc[dst_ground_count][dst_column]) + 1)
                        )
                        dst_ground_value.append(
                            ground_matrix.loc[dst_ground_count][dst_column + 1]
                        )
                        dst_ground_count = dst_ground_count + 1
            except KeyError:
                continue

            if src_ground not in ground_sat:
                continue

            src_sat = ground_sat[src_ground]
            dst_ground_value_count = 0
            for destination_ground in dst_ground:
                if destination_ground not in ground_sat:
                    dst_ground_value_count += 1
                    continue
                dst_sat = ground_sat[destination_ground]
                if src_sat != dst_sat:
                    value = dst_ground_value[dst_ground_value_count]
                    for Origin in src_sat:
                        if Origin not in sate_ref:
                            continue
                        for Destination in dst_sat:
                            if Destination not in sate_ref:
                                continue
                            if Origin != sate_ref[Destination]:
                                Destination = sate_ref[Destination]
                                sat_matrix[sate_ref[Origin]][Destination] = (
                                    sat_matrix[sate_ref[Origin]][Destination] + value
                                )
                dst_ground_value_count += 1

        sat_matrix_all.extend(sat_matrix)

        # 每个时间步保存一个 xlsx
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        for row in sat_matrix_all:
            sheet.append(row)
        Name = os.path.join(output_dir, str(j + 1) + '.xlsx')
        workbook.save(Name)
        sat_matrix_all = []

    print(f"[星间流量] 完成! {global_time} 个时间步输出至: {output_dir}")
    return output_dir


if __name__ == "__main__":
    generate_inter_satellite_traffic()
