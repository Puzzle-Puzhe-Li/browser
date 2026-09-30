"""读取速度 CSV：第一列 time（秒），其余列为各关节。"""
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MotionData:
    data: np.ndarray      # (n_joints, n_samples) float32
    names: list           # 关节名
    fs: float             # 采样率 (Hz)
    t_start: float        # 第一个样本的时间（CSV 的 time 列，秒）

    @property
    def duration(self):
        return self.data.shape[1] / self.fs


def load_speed_csv(path):
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [str(c).strip() for c in df.columns]
    tcol = "time" if "time" in df.columns else df.columns[0]
    t = df[tcol].to_numpy(dtype=float)
    names = [c for c in df.columns if c != tcol]
    vals = df[names].to_numpy(dtype=float).T                    # (n_joints, n)

    dt = float(np.median(np.diff(t)))
    if not np.allclose(np.diff(t), dt, rtol=1e-3, atol=1e-6):
        # 时间轴不均匀：插值到均匀网格（缺失值保持为 NaN）
        grid = np.arange(t[0], t[-1] + dt / 2, dt)
        vals = np.vstack([np.interp(grid, t, v) for v in vals])
        t = grid
    return MotionData(vals.astype(np.float32), names, 1.0 / dt, float(t[0]))
