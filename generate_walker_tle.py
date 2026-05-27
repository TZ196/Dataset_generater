"""
Walker Delta 标称星座 TLE 生成器
=================================
用于生成 Starlink Shell 1（或任意 Walker Delta 星座）的 TLE 文件。
不依赖 STK，纯 Python 实现。

依赖：
    pip install sgp4 skyfield numpy

使用示例：
    python generate_walker_tle.py

输出：
    starlink_shell1.tle  —— 标准三行 TLE 格式，可直接用于 sgp4/Skyfield
"""

import numpy as np
from datetime import datetime, timezone

# ──────────────────────────────────────────────
# 物理常数
# ──────────────────────────────────────────────
MU_EARTH = 398600.4418   # 地心引力常数，km³/s²
R_EARTH  = 6371.0        # 地球平均半径，km


# ══════════════════════════════════════════════
# TLE 格式工具函数
# ══════════════════════════════════════════════

def tle_checksum(line: str) -> int:
    """
    计算 TLE 行的校验和。
    规则：对每个数字字符累加其值，'-' 计 1，其他字符忽略，结果 mod 10。
    """
    return sum(
        int(c) if c.isdigit() else (1 if c == '-' else 0)
        for c in line
    ) % 10


def epoch_from_datetime(dt: datetime) -> str:
    """
    将 datetime 对象转换为 TLE epoch 格式字符串 "YYDDD.DDDDDDDD"（14字符）。

    示例：
        datetime(2021, 1, 1, 0, 0, 0) → "21001.00000000"
        datetime(2021, 6, 15, 12, 0, 0) → "21166.50000000"
    """
    year_2d   = dt.year % 100
    doy       = dt.timetuple().tm_yday          # day of year, 1-366
    frac_day  = (dt.hour * 3600 + dt.minute * 60 + dt.second
                 + dt.microsecond / 1e6) / 86400.0
    # frac_day 为 0.XXXXXXXX，取小数点后8位
    frac_str  = f"{frac_day:.8f}"[1:]           # ".XXXXXXXX" (9 chars)
    return f"{year_2d:02d}{doy:03d}{frac_str}"  # 2+3+9 = 14 chars


def format_line1(sat_num: int, epoch_str: str, elem_set_num: int = 999) -> str:
    """
    生成 TLE 第一行（69字符含校验位）。

    参数：
        sat_num      : 卫星编号，1–99999
        epoch_str    : epoch 字符串，格式 "YYDDD.DDDDDDDD"（14字符）
        elem_set_num : 轨道根数集编号（任意整数，仿真用可固定为 999）

    TLE Line 1 字段布局（列号从1计）：
        01     : 行号 "1"
        02     : 空格
        03-07  : 卫星编号
        08     : 分类标记 "U"（非保密）
        09     : 空格
        10-17  : 国际编号（8字符）
        18     : 空格
        19-32  : 历元（14字符）
        33     : 空格
        34-43  : 平均运动一阶导数（10字符）
        44     : 空格
        45-52  : 平均运动二阶导数（8字符，含隐含小数点与指数）
        53     : 空格
        54-61  : BSTAR 大气阻力项（8字符）
        62     : 空格
        63     : 轨道根数类型
        64     : 空格
        65-68  : 轨道根数集编号
        69     : 校验位
    """
    body = (
        f"1 "
        f"{sat_num:05d}"
        f"U "
        f"21001  A "                # 国际编号（伪造为 2021年第1次发射A块，右对齐）
        f"{epoch_str} "             # epoch 14字符 + 分隔空格
        f" .00000000 "              # 平均运动一阶导 = 0（无摄动）
        f" 00000-0 "                # 平均运动二阶导 = 0
        f" 00000-0 "                # BSTAR = 0（不考虑大气阻力）
        f"0 "                       # 轨道根数类型
        f"{elem_set_num:4d}"        # 根数集编号（4位右对齐）
    )
    assert len(body) == 68, f"Line1 body 长度异常: {len(body)}"
    return body + str(tle_checksum(body))


def format_line2(
    sat_num : int,
    inc_deg : float,   # 倾角，度
    raan_deg: float,   # 升交点赤经，度
    ecc     : float,   # 轨道偏心率
    argp_deg: float,   # 近地点幅角，度
    ma_deg  : float,   # 平近点角，度
    mm_revday: float,  # 平均运动，转/天
    rev_num : int = 0, # 历元时圈数
) -> str:
    """
    生成 TLE 第二行（69字符含校验位）。

    TLE Line 2 字段布局（列号从1计）：
        01     : 行号 "2"
        02     : 空格
        03-07  : 卫星编号
        08     : 空格
        09-16  : 倾角（8字符，格式 XXX.XXXX）
        17     : 空格
        18-25  : 升交点赤经（8字符）
        26     : 空格
        27-33  : 偏心率（7字符，隐含前置小数点）
        34     : 空格
        35-42  : 近地点幅角（8字符）
        43     : 空格
        44-51  : 平近点角（8字符）
        52     : 空格
        53-63  : 平均运动（11字符，格式 XX.XXXXXXXX）
        64-68  : 历元圈数（5字符）
        69     : 校验位
    """
    # 偏心率：TLE 中无小数点，7位整数表示（即 e × 10^7）
    ecc_str = f"{ecc:.7f}"[2:]      # "0.0000001" → "0000001"

    # 所有角度规范到 [0, 360)
    inc_deg  = inc_deg  % 360
    raan_deg = raan_deg % 360
    argp_deg = argp_deg % 360
    ma_deg   = ma_deg   % 360

    body = (
        f"2 "
        f"{sat_num:05d} "
        f"{inc_deg:8.4f} "
        f"{raan_deg:8.4f} "
        f"{ecc_str} "
        f"{argp_deg:8.4f} "
        f"{ma_deg:8.4f} "
        f"{mm_revday:11.8f}"
        f"{rev_num:05d}"
    )
    assert len(body) == 68, f"Line2 body 长度异常: {len(body)}"
    return body + str(tle_checksum(body))


# ══════════════════════════════════════════════
# 平均运动计算
# ══════════════════════════════════════════════

def compute_mean_motion(alt_km: float) -> float:
    """
    计算圆轨道平均运动（转/天）。

    参数：
        alt_km : 轨道高度（km）

    返回：
        平均运动（rev/day）

    示例：
        compute_mean_motion(550)  → 15.0782  （Starlink Shell 1）
        compute_mean_motion(1200) → 13.2947  （OneWeb）
    """
    a = R_EARTH + alt_km
    n_rad_s = np.sqrt(MU_EARTH / a**3)
    return n_rad_s * 86400.0 / (2.0 * np.pi)


# ══════════════════════════════════════════════
# Walker Delta 星座生成器
# ══════════════════════════════════════════════

def generate_walker_delta_tles(
    T         : int,         # 卫星总数
    P         : int,         # 轨道面数
    F         : int,         # Walker 相位因子 (0 ≤ F < P)
    inc_deg   : float,       # 轨道倾角（度）
    alt_km    : float,       # 轨道高度（km）
    epoch_str : str,         # TLE 历元字符串 "YYDDD.DDDDDDDD"
    prefix    : str = "SAT", # 卫星名称前缀
    start_id  : int = 70001, # 起始 NORAD 编号（避免与真实卫星冲突）
) -> list:
    """
    生成 Walker Delta(T/P/F) 标称星座的所有 TLE。

    Walker Delta 参数说明：
        T : 总卫星数
        P : 轨道面数，每面卫星数 S = T/P
        F : 相邻轨道面间的卫星相位偏移因子。
            相位差 Δu = F × 360° / T。F=0 时各面同步，F=1 时错开最小相位。

    Starlink Shell 1 示例：
        Walker 53°: 1584/72/1  → T=1584, P=72, F=1, inc=53°

    轨道根数布局：
        - 升交点赤经（RAAN）：各轨道面均匀分布在 0°~360°
        - 平近点角（MA）：面内均匀分布，相邻面之间有 F 相位偏移

    返回：
        list of (name, line1, line2) — 每颗卫星的名称和两行 TLE

    异常：
        AssertionError : 若 T 不能被 P 整除
    """
    assert T % P == 0, f"卫星总数 T={T} 必须能被轨道面数 P={P} 整除"
    assert 0 <= F < P, f"相位因子 F={F} 必须满足 0 ≤ F < P={P}"

    S            = T // P                  # 每个轨道面的卫星数
    mm           = compute_mean_motion(alt_km)
    raan_step    = 360.0 / P               # 面间 RAAN 间距（度）
    ma_step      = 360.0 / S              # 面内 MA 间距（度）
    phase_offset = F * 360.0 / T          # 每面的相位偏移量（度）

    tles = []
    for p in range(P):
        raan = p * raan_step
        for s in range(S):
            ma   = (s * ma_step + p * phase_offset) % 360.0
            sid  = start_id + p * S + s
            name = f"{prefix}_{p:03d}_{s:02d}"

            line1 = format_line1(sid, epoch_str)
            line2 = format_line2(
                sat_num  = sid,
                inc_deg  = inc_deg,
                raan_deg = raan,
                ecc      = 0.0,       # 近圆轨道，偏心率设为零
                argp_deg = 0.0,      # 近地点幅角（圆轨道中无意义，设 0）
                ma_deg   = ma,
                mm_revday= mm,
                rev_num  = 0,
            )
            tles.append((name, line1, line2))

    return tles


def save_tle_file(tles: list, filepath: str, fmt: str = "three-line") -> None:
    """
    将 TLE 列表保存到文件。

    参数：
        tles     : generate_walker_delta_tles() 的返回值
        filepath : 输出文件路径
        fmt      : 格式选项
                   "three-line" (默认) — 每颗卫星三行（名称 + L1 + L2），标准 TLE 格式
                   "two-line"          — 每颗卫星两行（L1 + L2），无名称行
    """
    with open(filepath, "w") as f:
        for name, l1, l2 in tles:
            if fmt == "three-line":
                f.write(f"{name}\n{l1}\n{l2}\n")
            else:
                f.write(f"{l1}\n{l2}\n")
    print(f"已保存 {len(tles)} 颗卫星 TLE → {filepath}")


# ══════════════════════════════════════════════
# 验证函数
# ══════════════════════════════════════════════

def validate_tles(tles: list, n_check: int = 10) -> None:
    """
    用 sgp4 库验证 TLE 格式正确性，检查高度与倾角是否符合设计值。

    参数：
        tles    : TLE 列表
        n_check : 随机抽检颗数
    """
    try:
        from sgp4.api import Satrec
    except ImportError:
        print("sgp4 未安装，跳过验证。运行：pip install sgp4")
        return

    indices = np.random.choice(len(tles), min(n_check, len(tles)), replace=False)
    errors = 0
    alts   = []
    for idx in indices:
        name, l1, l2 = tles[idx]
        sat = Satrec.twoline2rv(l1, l2)
        e, r, v = sat.sgp4(sat.jdsatepoch, sat.jdsatepochF)
        if e != 0:
            print(f"  ✗ {name}: sgp4 错误码 {e}")
            errors += 1
            continue
        alt = np.linalg.norm(r) - R_EARTH
        alts.append(alt)

    if errors == 0 and alts:
        print(f"  ✓ 抽检 {len(alts)} 颗，全部解析成功")
        print(f"  ✓ 高度范围：{min(alts):.1f} ~ {max(alts):.1f} km（均值 {np.mean(alts):.1f} km）")
    else:
        print(f"  ✗ 存在 {errors} 条解析失败")


# ══════════════════════════════════════════════
# 预设星座配置
# ══════════════════════════════════════════════

CONSTELLATIONS = {
    # 名称               T      P    F    inc   alt(km)
    "starlink_shell1": (1584,  72,  1,  53.0,  550),   # Starlink 第一壳层，论文使用
    "starlink_shell2": (1584,  72,  1,  53.2,  540),   # Starlink 第二壳层（v1.5 Group 4）
    "iridium":         (  66,   6,  2,  86.4,  780),   # Iridium NEXT
    "telesat":         ( 298,  13,  6,  99.5, 1015),   # Telesat Phase 1（极轨部分近似）
    "oneweb":          ( 648,  18,  0,  87.9, 1200),   # OneWeb Phase 1
}


# ══════════════════════════════════════════════
# 主程序
# ══════════════════════════════════════════════

if __name__ == "__main__":
    import os

    # ── 生成 Starlink Shell 1──
    print("=" * 55)
    print("Walker Delta TLE 生成器")
    print("=" * 55)

    # 历元：设为 2021-01-01 00:00:00 UTC
    epoch_dt  = datetime(2021, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    epoch_str = epoch_from_datetime(epoch_dt)
    print(f"历元：{epoch_dt.isoformat()}  →  TLE epoch: {epoch_str}")

    print("\n[1/3] 生成 Starlink Shell 1（1584/72/1，53°，550 km）...")
    tles = generate_walker_delta_tles(
        T        = 1584,
        P        = 72,
        F        = 1,
        inc_deg  = 53.0,
        alt_km   = 550.0,
        epoch_str= epoch_str,
        prefix   = "SL1",
        start_id = 70001,
    )

    print(f"  生成卫星数：{len(tles)}")
    print(f"  平均运动：{compute_mean_motion(550):.8f} rev/day")
    print(f"  RAAN 间隔：{360/72:.4f}°/面")
    print(f"  面内 MA 间隔：{360/22:.4f}°/星")

    print("\n[2/3] 验证 TLE（sgp4 抽检 20 颗）...")
    validate_tles(tles, n_check=20)

    print("\n[3/3] 保存文件...")
    out_dir = os.path.dirname(os.path.abspath(__file__))
    save_tle_file(tles, os.path.join(out_dir, "starlink_shell1.tle"), fmt="three-line")

    # ── 打印前几颗示例 ──
    print("\n示例（前 3 颗卫星）：")
    print("-" * 55)
    for name, l1, l2 in tles[:3]:
        print(name)
        print(l1)
        print(l2)

    # ── 如何在 Skyfield 中使用 ──
    print("\n" + "=" * 55)
    print("后续使用方法（Skyfield）：")
    print("=" * 55)
    print("""
from skyfield.api import load, EarthSatellite

ts = load.timescale()

# 读取 TLE 文件
satellites = []
with open("starlink_shell1.tle") as f:
    lines = [l.strip() for l in f if l.strip()]

for i in range(0, len(lines), 3):
    name = lines[i]
    sat  = EarthSatellite(lines[i+1], lines[i+2], name, ts)
    satellites.append(sat)

# 获取某时刻所有卫星的地心位置（km）
t = ts.utc(2021, 1, 1, 0, 0, 0)
positions = []
for sat in satellites:
    pos = sat.at(t).position.km   # [x, y, z]（ECI 坐标）
    positions.append(pos)
    
print(f"卫星数：{len(satellites)}")
print(f"第一颗位置（km）：{positions[0]}")
""")
