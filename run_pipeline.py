"""
卫星流量生成管线 — 一键编排
===========================
替代原有的 STK 依赖流程，纯 Python 实现。

Stage 0: 生成 TLE (generate_walker_tle) 或使用已有 TLE
Stage 1: 星地可见性计算 (visibility_module)
Stage 2: 地面站流量矩阵 (Ground_Traffic_Matrix)
Stage 3: 星间流量矩阵 (Inter_Satellite_Traffic_Matrix)
Stage 4: 星间邻接矩阵 (topology_module)

用法：
    # 全流程 — Iridium 星座
    python run_pipeline.py --constellation iridium --output-dir ./output

    # 全流程 — Starlink Shell 1
    python run_pipeline.py --constellation starlink_shell1 --duration 1000 --output-dir ./output

    # 使用已有 TLE 文件
    python run_pipeline.py --tle-file my_sats.tle --output-dir ./output

    # 只运行某几个阶段
    python run_pipeline.py --constellation iridium --stages tle,visibility
"""

import os
import sys
import argparse
from datetime import datetime, timezone

# 确保能 import 各子目录下的模块
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for subdir in ["tle", "visibility", "traffic", "topology"]:
    subdir_path = os.path.join(BASE_DIR, subdir)
    if subdir_path not in sys.path:
        sys.path.insert(0, subdir_path)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ──────────────────────────────────────────────
# 星座预设（与 generate_walker_tle.py 保持一致）
# ──────────────────────────────────────────────
CONSTELLATIONS = {
    "starlink_shell1": (1584, 72, 1, 53.0, 550),
    "starlink_shell2": (1584, 72, 1, 53.2, 540),
    "iridium":         (66,   6,  2, 86.4, 780),
    "telesat":         (298, 13,  6, 99.5, 1015),
    "oneweb":          (648, 18,  0, 87.9, 1200),
}


def parse_args():
    p = argparse.ArgumentParser(description="卫星流量生成管线")

    # 星座 / TLE
    g = p.add_mutually_exclusive_group()
    g.add_argument("--constellation", choices=list(CONSTELLATIONS.keys()),
                   help="使用预设星座，自动生成 TLE")
    g.add_argument("--tle-file", help="使用已有 TLE 文件（跳过 Stage 1）")

    # 通用参数
    p.add_argument("--stations", default=os.path.join(BASE_DIR, "data", "coor_station.xlsx"),
                   help="地面站坐标 xlsx (默认: data/coor_station.xlsx)")
    p.add_argument("--output-dir", default=os.path.join(BASE_DIR, "output"),
                   help="输出根目录 (默认: ./output)")
    p.add_argument("--duration", type=float, default=1000.0,
                   help="仿真时长(秒) (默认: 1000)")
    p.add_argument("--start-time", default="2021-01-01T00:00:00",
                   help="仿真起始 UTC 时间 (默认: 2021-01-01T00:00:00)")
    p.add_argument("--min-elevation", type=float, default=10.0,
                   help="最小可见仰角(度) (默认: 10)")
    p.add_argument("--workers", type=int, default=None,
                   help="并行进程数 (默认: CPU 核数)")

    # 流量参数
    p.add_argument("--offerload", type=float, default=0.1,
                   help="流量负载因子 (默认: 0.1)")
    p.add_argument("--band", type=float, default=1024,
                   help="链路带宽 Mbps (默认: 1024)")

    # 拓扑参数
    p.add_argument("--alt-km", type=float, default=None,
                   help="轨道高度 km (使用 --constellation 时自动获取, "
                        "使用 --tle-file 时需手动指定)")
    p.add_argument("--time-step", type=float, default=1.0,
                   help="拓扑/可见性时间步长秒 (默认: 1.0)")

    # 阶段控制
    p.add_argument("--stages", default="all",
                   help="运行的阶段: tle,visibility,ground,sat,topology 或用逗号组合, "
                        "或 'all' 运行全部 (默认: all)")
    p.add_argument("--tle-output", default=None,
                   help="TLE 输出文件名 (默认: 自动命名)")
    p.add_argument("--sat-prefix", default="SAT",
                   help="TLE 卫星名前缀 (默认: SAT)")
    p.add_argument("--start-id", type=int, default=70001,
                   help="起始 NORAD 编号 (默认: 70001)")

    return p.parse_args()


def parse_stages(stages_str):
    """解析阶段参数。"""
    if stages_str == "all":
        return ["tle", "visibility", "ground", "sat", "topology"]
    return [s.strip().lower() for s in stages_str.split(",")]


# ──────────────────────────────────────────────
# Stage 1: 生成 TLE
# ──────────────────────────────────────────────

def run_stage_tle(args, run_dirs):
    print("\n" + "=" * 55)
    print("Stage 1: 生成 TLE 文件")
    print("=" * 55)

    from generate_walker_tle import (
        generate_walker_delta_tles,
        save_tle_file,
        epoch_from_datetime,
    )

    T, P, F, inc, alt = CONSTELLATIONS[args.constellation]
    print(f"  星座: {args.constellation} (T={T}, P={P}, F={F}, inc={inc}°, alt={alt}km)")

    # 历元
    epoch_dt = datetime.fromisoformat(args.start_time)
    if epoch_dt.tzinfo is None:
        epoch_dt = epoch_dt.replace(tzinfo=timezone.utc)
    epoch_str = epoch_from_datetime(epoch_dt)

    tles = generate_walker_delta_tles(
        T=T, P=P, F=F, inc_deg=inc, alt_km=alt,
        epoch_str=epoch_str, prefix=args.sat_prefix, start_id=args.start_id,
    )

    # 输出文件名
    if args.tle_output:
        tle_path = os.path.join(run_dirs["tle"], args.tle_output)
    else:
        tle_path = os.path.join(run_dirs["tle"], f"{args.constellation}.tle")

    save_tle_file(tles, tle_path, fmt="three-line")
    print(f"  TLE 输出: {tle_path}  ({len(tles)} 颗卫星)")
    return tle_path


# ──────────────────────────────────────────────
# Stage 2: 星地可见性
# ──────────────────────────────────────────────

def run_stage_visibility(args, run_dirs, tle_path):
    print("\n" + "=" * 55)
    print("Stage 2: 星地可见性计算 (Skyfield)")
    print("=" * 55)

    from visibility_module import load_ground_stations, generate_all_visibility

    stations_df = load_ground_stations(args.stations)
    print(f"  地面站: {len(stations_df)} 个")

    start_dt = datetime.fromisoformat(args.start_time)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    start_tuple = (start_dt.year, start_dt.month, start_dt.day,
                   start_dt.hour, start_dt.minute, start_dt.second)

    satellite_names = generate_all_visibility(
        tle_path=tle_path,
        stations_df=stations_df,
        output_dir=run_dirs["visibility"],
        start_time_utc=start_tuple,
        duration_seconds=args.duration,
        min_elevation_deg=args.min_elevation,
        n_workers=args.workers,
    )
    return satellite_names


# ──────────────────────────────────────────────
# Stage 3: 地面站流量
# ──────────────────────────────────────────────

def run_stage_ground(args, run_dirs):
    print("\n" + "=" * 55)
    print("Stage 3: 地面站流量矩阵")
    print("=" * 55)

    from Ground_Traffic_Matrix import generate_ground_traffic

    return generate_ground_traffic(
        coordinate_path=args.stations,
        output_dir=run_dirs["ground"],
        global_time=int(args.duration),
        offerload=args.offerload,
        band=args.band,
    )


# ──────────────────────────────────────────────
# Stage 4: 星间流量矩阵
# ──────────────────────────────────────────────

def run_stage_satellite(args, run_dirs):
    print("\n" + "=" * 55)
    print("Stage 4: 星间流量矩阵")
    print("=" * 55)

    from Inter_Satellite_Traffic_Matrix import generate_inter_satellite_traffic

    return generate_inter_satellite_traffic(
        vis_dir=run_dirs["visibility"],
        ground_traffic_path=os.path.join(run_dirs["ground"], f"{int(args.duration)}.xlsx"),
        sat_names_path=os.path.join(run_dirs["visibility"], "satellite_names.xlsx"),
        output_dir=run_dirs["satellite"],
        global_time=int(args.duration),
    )


# ──────────────────────────────────────────────
# Stage 5: 星间邻接矩阵
# ──────────────────────────────────────────────

def run_stage_topology(args, run_dirs, tle_path, alt_km):
    print("\n" + "=" * 55)
    print("Stage 5: 星间邻接矩阵 (ISL Topology)")
    print("=" * 55)

    from topology_module import generate_adjacency_matrices

    if alt_km is None:
        print("  错误: 请指定 --alt-km 或使用 --constellation")
        sys.exit(1)

    start_dt = datetime.fromisoformat(args.start_time)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    start_tuple = (start_dt.year, start_dt.month, start_dt.day,
                   start_dt.hour, start_dt.minute, start_dt.second)

    return generate_adjacency_matrices(
        tle_path=tle_path,
        output_dir=run_dirs["topology"],
        alt_km=alt_km,
        start_time_utc=start_tuple,
        duration_seconds=args.duration,
        time_step_seconds=args.time_step,
    )


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def main():
    args = parse_args()
    stages = parse_stages(args.stages)

    # 构建子目录
    run_dirs = {
        "tle":        os.path.join(args.output_dir, "tle"),
        "visibility": os.path.join(args.output_dir, "visibility_output"),
        "ground":     os.path.join(args.output_dir, "ground_traffic"),
        "satellite":  os.path.join(args.output_dir, "inter_satellite_traffic"),
        "topology":   os.path.join(args.output_dir, "adjacency_matrices"),
    }
    for d in run_dirs.values():
        os.makedirs(d, exist_ok=True)

    # 确定 TLE 路径 + 轨道高度
    tle_path = args.tle_file
    alt_km = args.alt_km  # 用户指定的高度优先
    if args.constellation:
        _, _, _, _, alt_km = CONSTELLATIONS[args.constellation]  # 从预设获取

    if tle_path is None and "tle" not in stages:
        if not args.constellation:
            print("错误: 请指定 --constellation 或 --tle-file")
            sys.exit(1)
        stages = ["tle"] + stages

    print("=" * 55)
    print("卫星流量生成管线 (STK-Free)")
    print("=" * 55)
    print(f"  输出目录: {args.output_dir}")
    print(f"  仿真时长: {args.duration}s")
    print(f"  轨道高度: {alt_km} km" if alt_km else "  轨道高度: 未指定")
    print(f"  最小仰角: {args.min_elevation}°")
    print(f"  阶段: {', '.join(stages)}")

    # 执行各阶段
    for stage in stages:
        if stage == "tle":
            if args.tle_file:
                print(f"\n  使用已有 TLE: {args.tle_file}")
                tle_path = args.tle_file
            else:
                tle_path = run_stage_tle(args, run_dirs)
        elif stage == "visibility":
            run_stage_visibility(args, run_dirs, tle_path)
        elif stage == "ground":
            run_stage_ground(args, run_dirs)
        elif stage == "sat":
            run_stage_satellite(args, run_dirs)
        elif stage == "topology":
            run_stage_topology(args, run_dirs, tle_path, alt_km)
        else:
            print(f"  未知阶段: {stage}，跳过")

    print("\n" + "=" * 55)
    print("管线运行完成!")
    print(f"  输出目录: {args.output_dir}")
    print("=" * 55)


if __name__ == "__main__":
    main()
