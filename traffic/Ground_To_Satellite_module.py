import pandas as pd
import time

# 时间单位兼容：新 pipeline 输出秒，不再需要 *60 转换。
# 若有旧的 STK 分钟数据，将此值设为 60.0。
TIME_UNIT_MULTIPLIER = 1.0


def cal_ground_sat(g_time, data):
    last = 'target1'
    service_time = {}
    ground_sat = {}
    for i in range(data.shape[0]):
        ground = str(data.iloc[i, 0])
        sat = str(data.iloc[i, 1])
        start = TIME_UNIT_MULTIPLIER * float(data.iloc[i, 2])
        end = TIME_UNIT_MULTIPLIER * float(data.iloc[i, 3])

        if (ground != last):
            service_time = sorted(service_time.items(), key=lambda kv: (kv[1], kv[0]))
            non_zero_sat = [sat for sat, ser_time in service_time if ser_time != 0.0]
            if non_zero_sat:
                ground_sat[last] = non_zero_sat[-1]   # 论文: 选服务时间最长的1颗
            service_time = {}

        if (g_time >= start) & (g_time <= end):
            ser_time = end - g_time
            service_time[sat] = ser_time

        if (g_time < start):
            service_time[sat] = 0.0

        if (g_time > end):
            service_time[sat] = 0.0
        if (i + 1) == data.shape[0]:
            service_time = sorted(service_time.items(), key=lambda kv: (kv[1], kv[0]))
            non_zero_sat = [sat for sat, ser_time in service_time if ser_time != 0.0]
            if non_zero_sat:
                ground_sat[ground] = non_zero_sat[-1]  # 论文: 选服务时间最长的1颗
        last = ground

    return ground_sat