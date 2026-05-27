# STK-Free 卫星流量生成管线 — 设计方案与使用说明

## 概述

本管线从零开始生成卫星网络（LEO 星座）的**星间流量矩阵**（Inter-Satellite Traffic Matrix），不依赖 STK（Systems Tool Kit）等商业软件，纯 Python 实现。

**输入**：地面站经纬度坐标
**输出**：每个时间步的 N×N 卫星间流量矩阵，可直接用于卫星网络路由/资源分配等研究

### 为什么要替换 STK

原始管线中 `Scene_Generate_1.py` 调用 STK 11 COM API 计算星地可见性。STK 的问题：
- 需要购买 Windows 商业许可证
- COM API 只能运行在 Windows 上
- 不能自动化批处理
- 仿真时间硬编码为 720 秒，与下游 1000 时间步不匹配

本管线用 `skyfield` + `sgp4` 完全替代 STK，输出格式与原始 STK 输出 100% 兼容。

---

## 管线架构

```
                         ┌─────────────────────┐
                         │  generate_walker_tle │  Stage 0: 星座 TLE 生成
                         │  .py                 │
                         └──────────┬──────────┘
                                    │ .tle 文件
                                    ▼
┌──────────────┐          ┌─────────────────────┐
│ coor_station │──────────▶  visibility_module  │  Stage 1: 星地可见性 [NEW]
│ .xlsx        │          │  .py                │         (替代 STK)
└──────────────┘          └──────────┬──────────┘
                                     │ ground_{N}sawable.csv × 910
                                     │ satellite_names.xlsx
                                     ▼
                   ┌─────────────────────────────────┐
                   │  Ground_Traffic_Matrix.py        │  Stage 2: 地面站-地面站流量
                   │  + Temprol_module.py             │         GEANT 24h 曲线
                   │  + Spatial_module.py             │         时区 + 随机分发
                   └──────────────┬──────────────────┘
                                  │ 1000.xlsx (2000列)
                                  ▼
                   ┌─────────────────────────────────┐
                   │  Inter_Satellite_Traffic_Matrix  │  Stage 3: 地面流量→星间流量
                   │  + Ground_To_Satellite_module    │         可见性映射
                   └──────────────┬──────────────────┘
                                  │
                                  ▼
                     inter_satellite_traffic/
                     ├── 1.xlsx      ← 第 1 秒的卫星流量矩阵
                     ├── 2.xlsx      ← 第 2 秒的卫星流量矩阵
                     ├── ...
                     └── 1000.xlsx   ← 第 1000 秒的卫星流量矩阵

                                     │
                                     ▼
                   ┌─────────────────────────────────┐
                   │  topology_module.py              │  Stage 4: 星间邻接矩阵 [NEW]
                   │  SGP4 传播 + LOS 检测            │         0/1 ISL 拓扑
                   └──────────────┬──────────────────┘
                                  │
                                  ▼
                     adjacency_matrices/
                     ├── 1.xlsx      ← 第 1 秒的邻接矩阵 (N×N, 0/1)
                     ├── 2.xlsx      ← 第 2 秒的邻接矩阵
                     ├── ...
                     └── 1000.xlsx   ← 第 1000 秒的卫星流量矩阵
```

---

## 文件清单

### 新增文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `visibility_module.py` | ~280 | 核心：SGP4 传播 + 星地仰角计算 + 可见窗口检测 + CSV 输出 |
| `topology_module.py` | ~220 | 核心：SGP4 传播 + 卫星对 LOS 检测 + 邻接矩阵 0/1 输出 |
| `run_pipeline.py` | ~260 | 一键编排入口，命令行参数控制所有阶段 |
| `PIPELINE_DESIGN.md` | — | 本设计文档 |

### 从原 Dataset_generate 复制并修改的文件

| 文件 | 原目录 | 修改内容 |
|------|--------|----------|
| `generate_walker_tle.py` | `../` | TLE 格式修复：国际编号右对齐、偏心率设零 |
| `Ground_To_Satellite_module.py` | `Dataset_generate/` | 移除 `*60` 时间转换，添加显式 float 转换 |
| `Ground_Traffic_Matrix.py` | `Dataset_generate/` | 路径相对化，全局参数函数化 |
| `Inter_Satellite_Traffic_Matrix.py` | `Dataset_generate/` | 路径相对化，自动生成卫星名文件 |
| `Temprol_module.py` | `Dataset_generate/` | 删除模块级 `pd.read_excel()` 避免 import 报错 |
| `Spatial_module.py` | `Dataset_generate/` | 删除模块级 `pd.read_excel()` 避免 import 报错 |
| `coor_station.xlsx` | `Dataset_generate/` | 直接复制（910 站 × lat/lon） |


---

## 各阶段详细说明

### Stage 0: TLE 生成 (`generate_walker_tle.py`)

**功能**：根据 Walker Delta 星座参数生成标准三行格式 TLE 文件。

**内置星座预设**：

| 名称 | 卫星数 T | 轨道面 P | 相位 F | 倾角 | 高度 km |
|------|----------|----------|--------|------|---------|
| `iridium` | 66 | 6 | 2 | 86.4° | 780 |
| `starlink_shell1` | 1584 | 72 | 1 | 53.0° | 550 |
| `starlink_shell2` | 1584 | 72 | 1 | 53.2° | 540 |
| `telesat` | 298 | 13 | 6 | 99.5° | 1015 |
| `oneweb` | 648 | 18 | 0 | 87.9° | 1200 |

**输出格式**：三行格式（名称 + TLE Line1 + TLE Line2），兼容 sgp4 / skyfield。

**独立使用**：
```bash
python generate_walker_tle.py
# → starlink_shell1.tle (默认 Starlink Shell 1)
```

**关键参数**：
- `epoch`：仿真历元，默认 `2021-01-01 00:00:00 UTC`
- `start_id`：起始 NORAD 编号，默认 70001（避免冲突）
- `ecc`：偏心率固定为 0.0（标称圆轨道）

### Stage 1: 星地可见性计算 (`visibility_module.py`) [NEW]

**功能**：对每个地面站，计算所有卫星的可见时间窗口（rise/set），输出 CSV。

**算法**：
1. 解析三行格式 TLE，构建 `EarthSatellite` 对象列表
2. 对每个地面站 `(lat, lon, alt=0)`，构建 `wgs84.latlon()` 观测点
3. 调用 `sat.find_events(ground_pos, t0, t1, altitude_degrees=10.0)` 直接获取 rise/culminate/set 时间
4. 解析事件列表：配对 rise→set 为可见窗口
5. 处理边缘情况：
   - 仿真开始时卫星已在视野内（首个事件为 set）→ 从 t=0 开始
   - 仿真结束时卫星仍在视野内（末事件为 rise）→ 持续到 t=duration
   - 整个时段不可见 → 输出 `(start=0, end=0)`
6. 时间统一为相对仿真起点的**秒数**

**性能**：
- 使用 `multiprocessing.Pool` 按地面站并行
- Iridium (66 卫星 × 910 站) ≈ 2 小时（8 核）
- Starlink (1584 卫星 × 910 站) ≈ 5 小时（8 核）

**输出文件**：
```
visibility_output/
├── ground_1sawable.csv     # 地面站 target1 对 66 颗卫星的可见窗口
├── ground_2sawable.csv     # 地面站 target2 ...
├── ...
├── ground_910sawable.csv
└── satellite_names.xlsx     # 卫星名称列表（单列，供 Stage 3 使用）
```

**CSV 格式**（与 STK 输出一致）：
```csv
地面站节点,卫星节点,开始时间,结束时间
target1,SL1_000_00,0.0,234.5
target1,SL1_000_01,120.3,560.8
target1,SL1_000_02,0.0,0.0
...
```

**独立使用**：
```bash
python visibility_module.py \
  --tle-file starlink_shell1.tle \
  --stations coor_station.xlsx \
  --output-dir ./visibility_output \
  --duration 1000 \
  --min-elevation 10 \
  --workers 8
```

**关键参数**：
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--duration` | 1000.0 | 仿真时长（秒），必须 ≥ `global_time` |
| `--min-elevation` | 10.0 | 最小可见仰角（度），典型值 5-15° |
| `--workers` | CPU 核数 | 并行进程数 |

### Stage 2: 地面站流量矩阵 (`Ground_Traffic_Matrix.py`)

**功能**：生成 910 个地面站之间的流量需求矩阵，模拟互联网流量的时空特征。

**子模块**：

| 模块 | 功能 |
|------|------|
| `Temprol_module.py` | **时变模型**：使用 GEANT 骨干网 24 小时归一化曲线，按 UTC 时间 + 时区偏移分配权重 |
| `Spatial_module.py` | **空间模型**：统计每个时区的地面站数量，用时间种子随机分配流量 |

**流量生成算法**（每个时间步 j = 0..999）：

1. **时区权重**：`tem.calculate_zone_weight(g_time=j)` 返回 24 个时区的归一化权重
   - 根据 UTC 时 `math.floor(j / 3600)` 确定"当前峰值时区"
   - 以 GEANT 曲线为基础旋转权重分布
2. **总需求**：`demand = offerload × band × n_ter = 0.1 × 1024 × 910 = 93184`
3. **时区流量分配**：`zone_traffic[i] = zone_weight[i] × demand`
4. **站间分配**：每时区内按随机比例分给各站（种子=时间步，可复现）
5. **目的地选择**：每源站随机选 1-3 个目的站，**强制不同时区**

**输出格式**（`1000.xlsx`）：

每 2 列代表一个时间步，共 2000 列：
- 偶数列（0, 2, 4, ...）：目的地索引
- 奇数列（1, 3, 5, ...）：对应的流量值

行格式（每个源站）：
```
Row: *
     dest_index_1
     dest_index_2
     /
     *  (下一个源站)
```

**参数**：
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `offerload` | 0.1 | 流量负载因子（占总带宽的比例） |
| `band` | 1024 | 链路带宽（Mbps） |
| `global_time` | 1000 | 时间步数（秒级粒度） |

### Stage 3: 星间流量矩阵 (`Inter_Satellite_Traffic_Matrix.py`)

**功能**：将地面站-地面站流量映射为卫星-卫星流量矩阵。

**映射算法**（每个时间步 j）：

1. **星地关联**：`cal_ground_sat(g_time=j)` 查找每个地面站当前可见的卫星
   - 按剩余服务时间排序，优先选择即将切换的卫星
2. **流量映射**：对每对 `(源地面站 → 目的地面站)`：
   - 获取源站的可见卫星列表 `src_sats`
   - 获取目的站的可见卫星列表 `dst_sats`
   - 若 `src_sats == dst_sats`（同一卫星服务两端）→ **不产生星间流量**（星上交换）
   - 否则，将流量值加到所有 `(src_sat, dst_sat)` 对上
3. **输出**：66×66（Iridium）或 1584×1584（Starlink）的卫星流量矩阵

**输出**：
```
inter_satellite_traffic/
├── 1.xlsx      # 第 1 秒
├── 2.xlsx      # 第 2 秒
├── ...
└── 1000.xlsx   # 第 1000 秒
```

每个 Excel 文件包含一个 N_satellite × N_satellite 的二维矩阵。

### Stage 4: 星间邻接矩阵 (`topology_module.py`) [NEW]

**功能**：对每个时间步，生成 N×N 的 0/1 邻接矩阵，表示颗卫星之间是否存在星间链路（ISL）。

**算法**：
1. 解析 TLE，加载所有卫星
2. 对每个时间步，使用 SGP4 传播所有卫星的 ECI 位置 (x, y, z)
3. 对每对卫星 (i, j)，依次检查 ISL 条件：
   - **距离检查**：星间距离 ≤ 理论最大 LOS 距离 `2 × sqrt((R+h)² - R²)`
   - **视线检查**：两卫星连线不被地球遮挡（线段到地心最近距离 > R）
4. 若所有条件满足 → `adj[i][j] = adj[j][i] = 1`

**理论最大 ISL 距离**：

| 轨道高度 | 最大 ISL 距离 |
|----------|-------------|
| 550 km (Starlink) | ~5,358 km |
| 780 km (Iridium) | ~6,218 km |
| 1015 km (Telesat) | ~6,891 km |
| 1200 km (OneWeb) | ~7,334 km |

**输出格式**：

每个 `{step}.xlsx` 包含一个 N×N 的 DataFrame：
- **行 index** = 卫星名称 (如 `SL1_000_00`)
- **列 header** = 卫星名称
- **值** = 0 或 1

**独立使用**：
```bash
python topology_module.py \
  --tle-file iridium.tle \
  --alt-km 780 \
  --output-dir ./adjacency_output \
  --duration 1000 \
  --time-step 1.0
```

**关键参数**：
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--alt-km` | 780 | 轨道高度 (km)，决定最大 ISL 距离 |
| `--max-dist` | 自动计算 | 手动覆盖最大 ISL 距离 (km) |
| `--time-step` | 1.0 | 时间步长 (秒)，越小矩阵越密 |

**性能**：
- Iridium (66 卫星, 1000 步): ~5 分钟
- Starlink (1584 卫星, 1000 步): ~30 分钟（配对数多但位置批量计算）

---

## 数据流速查

| 从 | 到 | 数据 |
|---|---|---|
| `generate_walker_tle.py` | `visibility_module.py` | `.tle` TLE 轨道文件 |
| `coor_station.xlsx` | `visibility_module.py` | 910 站 lat/lon |
| `visibility_module.py` | `Inter_Satellite_Traffic_Matrix.py` | `ground_{N}sawable.csv` + `satellite_names.xlsx` |
| `coor_station.xlsx` | `Ground_Traffic_Matrix.py` | 910 站 lat/lon |
| `Ground_Traffic_Matrix.py` | `Inter_Satellite_Traffic_Matrix.py` | `1000.xlsx` 地面流量矩阵 |

---

## 关键设计决策

| 决策 | 理由 |
|------|------|
| **时间单位：秒** | skyfield 自然输出秒；原 STK 管线的 `*60` 转换是 bug（EpSec 已是秒） |
| **地面站海拔 = 0 km** | `coor_station.xlsx` 无高度列；LEO 轨道 ~7000km vs ±6km 海拔差异，仰角影响 < 0.05° |
| **最小仰角 = 10°** | 典型卫星通信最低仰角；与 STK 默认一致 |
| **`find_events()` 而非步进** | skyfield 内置函数直接输出 rise/set 时间，无需逐秒迭代，速度快 100 倍以上 |
| **多进程按站并行** | 每个地面站独立计算，天然可并行；8 核加速比约 6-7× |
| **1000 时间步 = 1000 秒** | 与原始管线 `global_time=1000` 一致 |
| **相对路径，无 D:\STK_Files** | 便于跨平台部署和 Git 管理 |

---

## 使用方法

### 依赖安装
```bash
pip install skyfield sgp4 numpy pandas openpyxl
```

### 一键运行全流程
```bash
cd Dataset_generater

# Iridium 星座 (推荐入门)
python run_pipeline.py --constellation iridium --output-dir ./output

# Starlink Shell 1 (1584 卫星，耗时长)
python run_pipeline.py --constellation starlink_shell1 --duration 1000 --output-dir ./output

# 使用已有 TLE 文件
python run_pipeline.py --tle-file my_sats.tle --output-dir ./output

# 只运行特定阶段
python run_pipeline.py --constellation iridium --stages tle,visibility
python run_pipeline.py --tle-file my_sats.tle --stages ground,sat
```

### `run_pipeline.py` 完整参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--constellation` | — | 预设星座：`iridium` / `starlink_shell1` / `starlink_shell2` / `telesat` / `oneweb` |
| `--tle-file` | — | 已有 TLE 文件路径（与 `--constellation` 互斥） |
| `--stations` | `./coor_station.xlsx` | 地面站坐标文件 |
| `--output-dir` | `./output` | 输出根目录 |
| `--duration` | 1000 | 仿真时长（秒） |
| `--start-time` | `2021-01-01T00:00:00` | 仿真起始 UTC 时间 |
| `--min-elevation` | 10.0 | 最小可见仰角（度） |
| `--workers` | CPU 核数 | 并行进程数 |
| `--offerload` | 0.1 | 流量负载因子 |
| `--band` | 1024 | 链路带宽（Mbps） |
| `--stages` | `all` | 阶段：`tle,visibility,ground,sat` 组合 |
| `--sat-prefix` | `SAT` | 卫星名前缀 |
| `--start-id` | 70001 | 起始 NORAD 编号 |

### 分步运行
```bash
# Step 1: 生成 TLE
python generate_walker_tle.py

# Step 2: 计算可见性
python visibility_module.py \
  --tle-file starlink_shell1.tle \
  --stations coor_station.xlsx \
  --output-dir ./visibility_output

# Step 3: 生成地面流量
python -c "from Ground_Traffic_Matrix import generate_ground_traffic; generate_ground_traffic()"

# Step 4: 生成星间流量
python -c "from Inter_Satellite_Traffic_Matrix import generate_inter_satellite_traffic; generate_inter_satellite_traffic()"
```

### 输出目录结构
```
output/
├── tle/
│   └── iridium.tle                           # Stage 0 输出
├── visibility_output/
│   ├── ground_1sawable.csv ... ground_910sawable.csv   # Stage 1 输出
│   └── satellite_names.xlsx                  # Stage 1 输出
├── ground_traffic/
│   └── 1000.xlsx                                # Stage 2 输出
├── inter_satellite_traffic/
│   ├── 1.xlsx ... 1000.xlsx                     # Stage 3 输出（流量矩阵）
└── adjacency_matrices/
    ├── 1.xlsx ... 1000.xlsx                     # Stage 4 输出（邻接矩阵 0/1）
```

---

## 与原始 STK 管线的差异

| 方面 | 原始管线 | 新管线 |
|------|----------|--------|
| 可见性计算 | STK 11 COM API (Windows only) | `skyfield.find_events()` (跨平台) |
| 时间单位 | 混乱：STK 输出 EpSec，但消费端 `*60` | 统一为秒 |
| 路径 | 硬编码 `D:\STK_Files\...` | 相对路径，可配置 |
| 卫星名文件 | 需预存 `iridum.xlsx` | 自动从 TLE 提取 |
| 仿真时长 | STK 场景 720s，global_time=1000s (不匹配) | 可配置，默认一致 |
| Ground_To_Satellite | `60*iloc[i][2]` (bug) | `float(iloc[i][2])` + `TIME_UNIT_MULTIPLIER=1.0` |

---

## 已知限制

1. **计算耗时**：Starlink 1584 卫星可见性计算约 5 小时（8 核），建议先在小星座上验证流程
2. **地面站海拔**：统一设 0，若需精确可用带高度的 `地面站.csv`
3. **SGP4 精度**：`sgp4` 库对极低轨道（< 200km）精度下降，本管线预设星座均在高轨道
4. **无大气折射模型**：`find_events()` 不包含大气折射修正（对 10° 以上仰角，折射误差 < 0.5°）
5. **非球形地球**：skyfield 使用 WGS84 椭球模型，与 STK 的 J2 摄动模型有微小差异（LEO 轨道周期误差 < 1s）
