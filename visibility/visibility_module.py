"""
星地可见性计算模块 (替代 STK)
==============================
使用 skyfield + sgp4 计算地面站与卫星之间的可见性窗口。
不依赖 STK，纯 Python 实现。

依赖：pip install skyfield sgp4 numpy pandas openpyxl

输出格式与 Scene_Generate_1.py (STK) 完全一致：
  CSV 列: 地面站节点, 卫星节点, 开始时间, 结束时间
  时间单位: 相对仿真起点的秒数
  文件命名: ground_{N}sawable.csv

用法：
  python visibility_module.py --tle-file starlink_shell1.tle --stations coor_station.xlsx
"""

import os
import sys
import argparse
import traceback
from datetime import datetime, timezone, timedelta
from multiprocessing import Pool, cpu_count

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────
# 加载 TLE
# ──────────────────────────────────────────────

def load_tles(tle_path, ts):
    """
    解析三行格式 TLE 文件（名称 + Line1 + Line2），返回卫星列表。

    参数：
        tle_path: TLE 文件路径
        ts:        skyfield load.timescale() 返回的时标对象

    返回：
        list of (name: str, sat: EarthSatellite)
    """
    from skyfield.api import EarthSatellite

    satellites = []
    with open(tle_path, 'r') as f:
        lines = [l.strip() for l in f if l.strip()]

    for i in range(0, len(lines), 3):
        if i + 2 >= len(lines):
            break
        name = lines[i]
        try:
            sat = EarthSatellite(lines[i+1], lines[i+2], name, ts)
            satellites.append((name, sat))
        except Exception:
            print(f"  [警告] 跳过卫星 {name}: TLE 解析失败")

    return satellites


def extract_satellite_names(tle_path):
    """从 TLE 文件中提取所有卫星名称（单列 DataFrame）。"""
    names = []
    with open(tle_path, 'r') as f:
        lines = [l.strip() for l in f if l.strip()]
    for i in range(0, len(lines), 3):
        if i + 2 >= len(lines):
            break
        names.append(lines[i])
    return pd.DataFrame(names)


# ──────────────────────────────────────────────
# 加载地面站
# ──────────────────────────────────────────────

def load_ground_stations(xlsx_path):
    """
    读取地面站坐标 Excel 文件。

    参数：
        xlsx_path: xlsx 文件路径，需包含 'lat' 和 'lon' 列

    返回：
        DataFrame，列: name, lat, lon, alt_km
    """
    df = pd.read_excel(xlsx_path, usecols=['lat', 'lon'])
    df['name'] = [f'target{i+1}' for i in range(len(df))]
    df['alt_km'] = 0.0
    return df


# ──────────────────────────────────────────────
# 可见性计算（单站 — 多进程 worker）
# ──────────────────────────────────────────────

def _worker_visibility(args):
    """
    多进程 worker: 对单个地面站计算所有卫星的可见窗口。

    参数 args 为元组：
        (station_name, station_lat, station_lon, station_alt_km,
         tle_path, start_dt_iso, duration_seconds, min_elevation_deg)

    返回：
        DataFrame，列: 地面站节点, 卫星节点, 开始时间, 结束时间
    """
    (station_name, lat, lon, alt_km,
     tle_path, start_dt_iso, duration_seconds, min_elevation_deg) = args

    from skyfield.api import load, EarthSatellite, wgs84

    ts = load.timescale()

    # 每个 worker 独立加载 TLE（避免跨进程序列化问题）
    satellites = []
    with open(tle_path, 'r') as f:
        lines = [l.strip() for l in f if l.strip()]
    for i in range(0, len(lines), 3):
        if i + 2 >= len(lines):
            break
        try:
            satellites.append((
                lines[i],
                EarthSatellite(lines[i+1], lines[i+2], lines[i], ts)
            ))
        except Exception:
            pass

    # 地面站位置
    ground_pos = wgs84.latlon(lat, lon, elevation_m=alt_km * 1000.0)

    # 仿真时间范围
    t0_dt = datetime.fromisoformat(start_dt_iso)
    t0 = ts.from_datetime(t0_dt)
    t1 = ts.from_datetime(t0_dt + timedelta(seconds=duration_seconds))

    rows = []
    for sat_name, sat in satellites:
        try:
            times, events = sat.find_events(
                ground_pos, t0, t1, altitude_degrees=min_elevation_deg
            )
        except Exception:
            rows.append([station_name, sat_name, 0.0, 0.0])
            continue

        if len(times) == 0:
            # 无升降事件: 检查卫星是否全程可见
            t_mid = ts.from_datetime(t0_dt + timedelta(seconds=duration_seconds / 2))
            alt, _, _ = (sat - ground_pos).at(t_mid).altaz()
            if alt.degrees >= min_elevation_deg:
                rows.append([station_name, sat_name, 0.0, float(duration_seconds)])
            else:
                rows.append([station_name, sat_name, 0.0, 0.0])
            continue

        # 解析 rise/set 事件
        # events: 0=rise, 1=culminate(max alt), 2=set
        rise_time = None
        has_window = False

        for ti, ev in zip(times, events):
            elapsed = (ti.utc_datetime() - t0_dt).total_seconds()
            elapsed = max(0.0, min(elapsed, float(duration_seconds)))

            if ev == 0:  # rise
                rise_time = elapsed
            elif ev == 2:  # set
                if rise_time is not None:
                    if elapsed > rise_time:
                        rows.append([station_name, sat_name, rise_time, elapsed])
                        has_window = True
                    rise_time = None
                else:
                    # 仿真开始时卫星已在仰角上方（第一个事件是 set）
                    if elapsed > 0:
                        rows.append([station_name, sat_name, 0.0, elapsed])
                        has_window = True
            # ev == 1 (culminate): 忽略

        # 仿真结束时卫星仍可见
        if rise_time is not None:
            rows.append([station_name, sat_name, rise_time, float(duration_seconds)])
            has_window = True

        if not has_window:
            rows.append([station_name, sat_name, 0.0, 0.0])

    return pd.DataFrame(rows, columns=['地面站节点', '卫星节点', '开始时间', '结束时间'])


# ──────────────────────────────────────────────
# 批量生成所有地面站可见性文件
# ──────────────────────────────────────────────

def generate_all_visibility(
    tle_path,
    stations_df,
    output_dir,
    start_time_utc=None,
    duration_seconds=1000.0,
    min_elevation_deg=10.0,
    n_workers=None,
    file_prefix="ground",
):
    """
    批量生成所有地面站的星地可见性 CSV 文件。

    参数：
        tle_path:           TLE 文件路径
        stations_df:        load_ground_stations() 返回的 DataFrame
        output_dir:         输出目录
        start_time_utc:     (year, month, day, hour, minute, second) 仿真起始 UTC
        duration_seconds:   仿真时长（秒）
        min_elevation_deg:  最小可见仰角（度）
        n_workers:          并行进程数（默认 cpu_count）
        file_prefix:        输出文件名前缀

    输出：
        {output_dir}/{file_prefix}_{i}sawable.csv  (i 从 1 开始)
        同时输出 {output_dir}/satellite_names.xlsx（卫星名列表）

    返回：
        list of str: 所有卫星名称
    """
    from skyfield.api import load

    if start_time_utc is None:
        start_time_utc = (2021, 1, 1, 0, 0, 0.0)

    t0_dt = datetime(*start_time_utc, tzinfo=timezone.utc)
    start_dt_iso = t0_dt.isoformat()

    if n_workers is None:
        n_workers = min(cpu_count(), len(stations_df))

    os.makedirs(output_dir, exist_ok=True)

    # 提取所有卫星名称
    sat_names_df = extract_satellite_names(tle_path)
    sat_names_path = os.path.join(output_dir, "satellite_names.xlsx")
    sat_names_df.to_excel(sat_names_path, index=False, header=None)
    print(f"[visibility] 卫星名称列表已保存: {sat_names_path}  ({len(sat_names_df)} 颗)")

    # 提取卫星名称列表
    with open(tle_path, 'r') as f:
        lines = [l.strip() for l in f if l.strip()]
    satellite_names = [lines[i] for i in range(0, len(lines), 3) if i + 2 < len(lines)]

    # 构建多进程参数
    tasks = []
    for idx, (_, row) in enumerate(stations_df.iterrows()):
        tasks.append((
            row['name'], row['lat'], row['lon'], row['alt_km'],
            tle_path, start_dt_iso, duration_seconds, min_elevation_deg
        ))

    total = len(tasks)
    print(f"[visibility] 开始计算 {total} 个地面站的可见性（{n_workers} 进程）...")
    print(f"[visibility] 星座: {len(satellite_names)} 颗卫星, "
          f"仿真时长: {duration_seconds}s, 最小仰角: {min_elevation_deg}°")

    with Pool(processes=n_workers) as pool:
        for i, result_df in enumerate(pool.imap_unordered(_worker_visibility, tasks)):
            # 从 DataFrame 中提取站名（取第一行第一列）
            if len(result_df) == 0:
                continue
            station_name = result_df.iloc[0, 0]
            # 提取站号: 'target42' -> 42
            try:
                station_num = int(station_name.replace('target', ''))
            except ValueError:
                # fallback: 使用 index
                station_num = i + 1

            csv_path = os.path.join(output_dir, f"{file_prefix}_{station_num}sawable.csv")
            result_df.to_csv(csv_path, index=False, encoding='utf_8_sig')

            if (i + 1) % 50 == 0 or (i + 1) == total:
                print(f"  [{i+1}/{total}] 已处理 {i+1} 个地面站...")

    print(f"[visibility] 完成! CSV 文件输出至: {output_dir}")
    return satellite_names


# ──────────────────────────────────────────────
# 串联所有 CSV 为单 DataFrame (供 Stage 3 使用)
# ──────────────────────────────────────────────

def concatenate_visibility_files(vis_dir, file_prefix="ground", n_stations=910):
    """
    将分散的 per-station CSV 文件串联为单一 DataFrame，
    与 Inter_Satellite_Traffic_Matrix.py 中手动拼接的逻辑等价。

    参数：
        vis_dir:      可见性 CSV 所在目录
        file_prefix:  文件名前缀
        n_stations:   地面站数量

    返回：
        pd.DataFrame (所有站的可见性数据纵向拼接)
    """
    first_path = os.path.join(vis_dir, f"{file_prefix}_1sawable.csv")
    if not os.path.exists(first_path):
        raise FileNotFoundError(f"未找到可见性文件: {first_path}")

    data = pd.read_csv(first_path)
    for i in range(2, n_stations + 1):
        path = os.path.join(vis_dir, f"{file_prefix}_{i}sawable.csv")
        if os.path.exists(path):
            data = pd.concat([data, pd.read_csv(path)], ignore_index=True)
    return data


# ──────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="星地可见性计算 (替代 STK)")
    parser.add_argument("--tle-file", required=True, help="TLE 文件路径（三行格式）")
    parser.add_argument("--stations", required=True, help="地面站坐标 xlsx 文件")
    parser.add_argument("--output-dir", default="./visibility_output", help="输出目录")
    parser.add_argument("--duration", type=float, default=1000.0, help="仿真时长 (秒)")
    parser.add_argument("--min-elevation", type=float, default=10.0, help="最小可见仰角 (度)")
    parser.add_argument("--workers", type=int, default=None, help="并行进程数")
    parser.add_argument("--prefix", default="ground", help="输出文件名前缀")

    args = parser.parse_args()

    print("=" * 55)
    print("[visibility] 星地可见性计算 (Skyfield)")
    print("=" * 55)

    stations_df = load_ground_stations(args.stations)
    print(f"[visibility] 地面站: {len(stations_df)} 个")
    print(f"[visibility] TLE 文件: {args.tle_file}")

    generate_all_visibility(
        tle_path=args.tle_file,
        stations_df=stations_df,
        output_dir=args.output_dir,
        duration_seconds=args.duration,
        min_elevation_deg=args.min_elevation,
        n_workers=args.workers,
        file_prefix=args.prefix,
    )
