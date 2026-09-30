"""读取 BDF/EDF，降采样到 TARGET_FS，返回 float32 (µV)。结果缓存到 CACHE_DIR。"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import mne
from scipy.signal import resample_poly

import config


@dataclass
class EEGData:
    data: np.ndarray      # (n_ch, n_samples) float32, µV
    names: list           # 通道名
    fs: float             # 降采样后的采样率

    @property
    def duration(self):
        return self.data.shape[1] / self.fs


def _open_raw(path):
    ext = Path(path).suffix.lower()
    if ext == ".bdf":
        return mne.io.read_raw_bdf(path, preload=False, verbose="ERROR")
    if ext == ".edf":
        return mne.io.read_raw_edf(path, preload=False, verbose="ERROR")
    raise ValueError(f"不支持的文件类型: {ext}")


def _decimate_chunked(raw, picks, factor, progress):
    """分块读取 + 整数倍抗混叠降采样。块两侧留余量，避免块边界的滤波瞬态。"""
    n_in = raw.n_times
    n_out = -(-n_in // factor)
    out = np.empty((len(picks), n_out), dtype=np.float32)
    chunk_out = 60_000       # 每块输出样本数（500 Hz 下 120 s）
    margin_out = 1_000       # 两侧余量（500 Hz 下 2 s）
    n_chunks = -(-n_out // chunk_out)
    dc = None                # 各通道直流偏置（取第一块的中位数），在转 float32 前先减掉以保精度
    for k, s_out in enumerate(range(0, n_out, chunk_out)):
        e_out = min(s_out + chunk_out, n_out)
        rs = max(0, (s_out - margin_out) * factor)
        re = min(n_in, (e_out + margin_out) * factor)
        x = raw.get_data(picks=picks, start=rs, stop=re)          # 伏特, float64
        y = resample_poly(x, 1, factor, axis=1, padtype="mean")
        off = s_out - rs // factor
        y = y[:, off:off + (e_out - s_out)] * 1e6                 # µV, float64
        if dc is None:
            dc = np.median(y, axis=1, keepdims=True)
        out[:, s_out:e_out] = (y - dc).astype(np.float32)
        if progress:
            progress(0.05 + 0.85 * (k + 1) / n_chunks, f"读取并降采样 {k + 1}/{n_chunks}")
    return out


def load_eeg(path, target_fs=config.TARGET_FS, progress=None, use_cache=True):
    path = Path(path)
    st = path.stat()
    cache_file = config.CACHE_DIR / f"{path.stem}_{st.st_size}_{int(st.st_mtime)}_{int(target_fs)}.npz"

    if use_cache and cache_file.exists():
        if progress:
            progress(0.5, "读取缓存…")
        z = np.load(cache_file)
        return EEGData(z["data"], [str(s) for s in z["names"]], float(z["fs"]))

    if progress:
        progress(0.02, "打开文件…")
    raw = _open_raw(str(path))
    fs = raw.info["sfreq"]
    types = raw.get_channel_types()
    picks = [i for i, t in enumerate(types) if t != "stim"]      # 排除 Status/触发通道
    names = [raw.ch_names[i] for i in picks]

    ratio = fs / target_fs
    if ratio >= 1 and abs(ratio - round(ratio)) < 1e-6:
        data = _decimate_chunked(raw, picks, int(round(ratio)), progress)
    else:
        # 非整数倍：退回 MNE 整段重采样（占内存较大）
        if progress:
            progress(0.1, "非整数倍降采样，整段载入中（较慢）…")
        raw.load_data()
        raw.pick(picks)
        raw.resample(target_fs, verbose="ERROR")
        data = (raw.get_data() * 1e6).astype(np.float32)
        names = list(raw.ch_names)

    data -= np.median(data, axis=1, keepdims=True).astype(np.float32)   # 去掉各通道直流偏置
    eeg = EEGData(data, names, float(target_fs))

    if use_cache:
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if progress:
            progress(0.95, "写入缓存…")
        np.savez(cache_file, data=data, names=np.array(names), fs=float(target_fs))
    if progress:
        progress(1.0, "完成")
    return eeg
