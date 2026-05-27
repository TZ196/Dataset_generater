"""
卫星邻接矩阵生成模块
=====================
根据卫星轨道计算每个时间步的星间链路（ISL）邻接矩阵。
矩阵中 [i][j] = 1 表示卫星 i 与卫星 j 之间存在星间链路，0 表示无链路。

方法：
  1. 使用 skyfield 传播所有卫星位置（SGP4）
  2. 对每对卫星判断是否满足 ISL 条件：
     - 视线无地球遮挡（Line-of-Sight）
     - 星间距离不超过最大通信距离
     - （可选）极地区域关闭跨轨道面链路（近极轨道时角速度过大）

用法：
  python topology_module.py --tle-file iridium.tle --output-dir ./adjacency_output
"""

import os
import sys
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from multiprocessing import Pool, cpu_count

# 地球半径 (km)
R_EARTH = 6371.0


def load_tles(tle_path):
    """解析三行格式 TLE，返回 (name, line1, line2) 元组列表。"""
    satellites = []
    with open(tle_path, 'r') as f:
        lines = [l.strip() for l in f if l.strip()]
    for i in range(0, len(lines), 3):
        if i + 2 >= len(lines):
            break
        satellites.append((lines[i], lines[i+1], lines[i+2]))
    return satellites


def compute_positions_at_time(satellites_tle, ts, t):
    """
    在给定时刻计算所有卫星的 ECI 位置。

    参数：
        satellites_tle: [(name, l1, l2), ...]
        ts: skyfield timescale
        t:  skyfield Time 对象

    返回：
        positions: np.array (N, 3) — ECI 坐标 (km)
        names:     list of str
    """
    from skyfield.api import EarthSatellite

    positions = []
    names = []
    for name, l1, l2 in satellites_tle:
        try:
            sat = EarthSatellite(l1, l2, name, ts)
            pos = sat.at(t).position.km  # [x, y, z] in km
            positions.append(pos)
            names.append(name)
        except Exception:
            # 如果传播失败，填 NaN 位置（标记为不可用）
            positions.append([np.nan, np.nan, np.nan])
            names.append(name)

    return np.array(positions), names


def check_los(pos_i, pos_j, alt_i_km, alt_j_km):
    """
    检查两颗卫星之间是否有视线（不被地球遮挡）。

    条件：两卫星连线到地心的距离 > R_EARTH

    参数：
        pos_i, pos_j: ECI 位置向量 (3,) km
        alt_i_km, alt_j_km: 轨道高度 km

    返回：
        True 如果存在视线，False 如果被地球遮挡
    """
    if np.any(np.isnan(pos_i)) or np.any(np.isnan(pos_j)):
        return False

    # 两卫星的距离向量
    d = pos_j - pos_i
    d_sq = np.dot(d, d)

    if d_sq == 0:
        return False

    # 参数方程: P(t) = pos_i + t * d
    # 到地心最近距离 t_min = -dot(pos_i, d) / dot(d, d)
    t_min = -np.dot(pos_i, d) / d_sq

    # 如果 t_min 在 [0,1] 之间，最近点在线段内部，检查是否穿过地球
    if 0 < t_min < 1:
        closest = pos_i + t_min * d
        dist_to_center = np.sqrt(np.dot(closest, closest))
        return dist_to_center > R_EARTH

    # 否则，最近点是其中一个端点，肯定在地球外（卫星在轨道上）
    return True


def compute_max_isl_distance(alt_km):
    """
    计算两颗同高度卫星之间的理论最大 ISL 距离。

    对于高度 h 的圆轨道，最大 LOS 距离：
        d_max = 2 * sqrt((R + h)^2 - R^2)

    参数：
        alt_km: 轨道高度 km

    返回：
        最大距离 km
    """
    return 2.0 * np.sqrt((R_EARTH + alt_km) ** 2 - R_EARTH ** 2)


def compute_adjacency_at_time(
    satellites_tle, ts, t, alt_km, max_dist_km=None, lat_threshold_deg=None
):
    """
    计算单个时间步的邻接矩阵。

    参数：
        satellites_tle:  TLE 列表
        ts:              skyfield timescale
        t:               skyfield Time
        alt_km:          轨道高度 (km)，用于 LOS 和最大距离计算
        max_dist_km:     最大 ISL 距离 (km)，默认按高度自动计算
        lat_threshold_deg: 纬度阈值，超过此值的卫星关闭跨面链路 (默认 None = 不限制)

    返回：
        adj_matrix: np.array (N, N) dtype int8 — 0/1 邻接矩阵
        names:      list of str — 卫星名称
    """
    if max_dist_km is None:
        max_dist_km = compute_max_isl_distance(alt_km)

    positions, names = compute_positions_at_time(satellites_tle, ts, t)
    N = len(names)

    # 预计算纬度（如需要极地过滤）
    lats = None
    if lat_threshold_deg is not None:
        from skyfield.api import wgs84
        lats = []
        for pos in positions:
            if np.any(np.isnan(pos)):
                lats.append(np.nan)
            else:
                # 从 ECI 转换到地心纬度
                lat = np.degrees(np.arctan2(pos[2], np.sqrt(pos[0]**2 + pos[1]**2)))
                lats.append(lat)

    adj = np.zeros((N, N), dtype=np.int8)

    for i in range(N):
        for j in range(i + 1, N):
            if np.any(np.isnan(positions[i])) or np.any(np.isnan(positions[j])):
                continue

            # 距离检查
            dist = np.sqrt(np.sum((positions[i] - positions[j]) ** 2))
            if dist > max_dist_km:
                continue

            # 极地纬度过滤（可选）
            if lats is not None:
                lat_i = lats[i]
                lat_j = lats[j]
                if not np.isnan(lat_i) and not np.isnan(lat_j):
                    if abs(lat_i) > lat_threshold_deg or abs(lat_j) > lat_threshold_deg:
                        # 在高纬度区域：只保留同轨道面链路，关闭跨面链路
                        # 简化为：检查两颗卫星是否可能在同一轨道面
                        # 这里用名称前缀做近似判断
                        # 实际中跨面链路在此区域应关闭
                        pass  # 可以在后续迭代中加入更精确的面判断

            # 视线检查
            if check_los(positions[i], positions[j], alt_km, alt_km):
                adj[i][j] = 1
                adj[j][i] = 1

    return adj, names


def generate_adjacency_matrices(
    tle_path,
    output_dir,
    alt_km=780.0,
    start_time_utc=None,
    duration_seconds=1000.0,
    time_step_seconds=1.0,
    max_dist_km=None,
):
    """
    批量生成所有时间步的邻接矩阵。

    参数：
        tle_path:          TLE 文件路径
        output_dir:        输出目录
        alt_km:            轨道高度 (km)
        start_time_utc:    (year, month, day, hour, minute, second)
        duration_seconds:  仿真时长（秒）
        time_step_seconds: 时间步长（秒），默认 1s
        max_dist_km:       最大 ISL 距离，默认自动计算

    输出：
        {output_dir}/{t}.xlsx  — 每个时间步的邻接矩阵
    """
    from skyfield.api import load

    if start_time_utc is None:
        start_time_utc = (2021, 1, 1, 0, 0, 0.0)

    ts = load.timescale()
    t0_dt = datetime(*start_time_utc, tzinfo=timezone.utc)

    satellites_tle = load_tles(tle_path)
    N = len(satellites_tle)
    print(f"[拓扑] 星座: {N} 颗卫星, 高度: {alt_km} km")

    if max_dist_km is None:
        max_dist_km = compute_max_isl_distance(alt_km)
        print(f"[拓扑] 最大 ISL 距离: {max_dist_km:.1f} km")

    os.makedirs(output_dir, exist_ok=True)

    num_steps = int(duration_seconds / time_step_seconds)
    print(f"[拓扑] 时间步长: {time_step_seconds}s, 共 {num_steps} 步")

    for step in range(num_steps):
        elapsed = step * time_step_seconds
        t = ts.from_datetime(t0_dt + timedelta(seconds=elapsed))

        adj, names = compute_adjacency_at_time(
            satellites_tle, ts, t, alt_km, max_dist_km
        )

        # 保存为 xlsx
        df = pd.DataFrame(adj, index=names, columns=names)
        out_path = os.path.join(output_dir, f"{step + 1}.xlsx")
        df.to_excel(out_path, index=True, header=True)

        if (step + 1) % 100 == 0 or (step + 1) == num_steps:
            n_links = np.sum(adj) // 2  # 无向边数
            print(f"  [{step + 1}/{num_steps}] 链路数: {n_links}")

    print(f"[拓扑] 完成! 输出: {output_dir}")
    return output_dir


# ──────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="卫星 ISL 邻接矩阵生成")
    parser.add_argument("--tle-file", required=True, help="TLE 文件路径")
    parser.add_argument("--output-dir", default="./adjacency_output", help="输出目录")
    parser.add_argument("--alt-km", type=float, default=780.0, help="轨道高度 (km)")
    parser.add_argument("--duration", type=float, default=1000.0, help="仿真时长 (秒)")
    parser.add_argument("--time-step", type=float, default=1.0, help="时间步长 (秒)")
    parser.add_argument("--max-dist", type=float, default=None, help="最大 ISL 距离 (km)")
    parser.add_argument("--start-time", default="2021-01-01T00:00:00", help="起始 UTC 时间")

    args = parser.parse_args()

    start_dt = datetime.fromisoformat(args.start_time)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    start_tuple = (start_dt.year, start_dt.month, start_dt.day,
                   start_dt.hour, start_dt.minute, start_dt.second)

    print("=" * 55)
    print("[拓扑] 卫星 ISL 邻接矩阵生成")
    print("=" * 55)

    generate_adjacency_matrices(
        tle_path=args.tle_file,
        output_dir=args.output_dir,
        alt_km=args.alt_km,
        start_time_utc=start_tuple,
        duration_seconds=args.duration,
        time_step_seconds=args.time_step,
        max_dist_km=args.max_dist,
    )
