"""时频面板：显示当前 WINDOW_SEC 窗口内单个通道的 TFR（dB），播放头固定在正中。

整段数据对选定通道只计算一次（Morlet 小波，分块 + 降采样），之后每帧只切片显示。
功率单位：数据 µV 先转为 V，再 10*log10(V^2)。
"""
import hashlib

import numpy as np
import pyqtgraph as pg
from mne.time_frequency import tfr_array_morlet
from pyqtgraph.Qt import QtCore, QtWidgets

import config


def jet_lut(n=256):
    """与 matplotlib 'jet' 近似的查找表，返回 (n, 3) uint8。"""
    x = np.linspace(0.0, 1.0, n)
    r = np.clip(1.5 - np.abs(4 * x - 3), 0, 1)
    g = np.clip(1.5 - np.abs(4 * x - 2), 0, 1)
    b = np.clip(1.5 - np.abs(4 * x - 1), 0, 1)
    return (np.stack([r, g, b], axis=1) * 255).astype(np.uint8)


def compute_tfr_db(x_uv, fs, freqs, n_cycles, out_fs, progress=None):
    """x_uv: (n_samples,) µV。返回 (n_freqs, n_out) float32 dB，时间分辨率 out_fs。
    第 k 列对应时间 k / out_fs（秒）。"""
    decim = max(1, int(round(fs / out_fs)))
    n = x_uv.shape[0]
    n_out = -(-n // decim)
    out = np.empty((len(freqs), n_out), dtype=np.float32)

    chunk = 60_000 - (60_000 % decim)          # 每块输入样本数（500 Hz 下约 120 s），为 decim 整数倍
    margin = 5_000 - (5_000 % decim)           # 两侧余量（500 Hz 下 10 s），也是 decim 整数倍
    n_chunks = -(-n // chunk)
    for k, s in enumerate(range(0, n, chunk)):
        e = min(s + chunk, n)
        rs = max(0, s - margin)
        re_ = min(n, e + margin)
        x = (x_uv[rs:re_].astype(np.float64) * 1e-6)[None, None, :]      # → V
        p = tfr_array_morlet(x, fs, freqs, n_cycles=n_cycles,
                             output="power", decim=decim, n_jobs=1, verbose="ERROR")[0, 0]
        off = (s - rs) // decim
        cnt = -(-(e - s) // decim)
        seg = p[:, off:off + cnt]
        out[:, s // decim: s // decim + seg.shape[1]] = (10.0 * np.log10(seg + 1e-30)).astype(np.float32)
        if progress:
            progress((k + 1) / n_chunks)
    return out


class TFRPanel(QtWidgets.QWidget):
    def __init__(self, data, names, fs, clock, axis_zero=0.0, cache_tag="",
                 channel=None, parent=None):
        super().__init__(parent)
        self.data = data
        self.names = [n.strip() for n in names]
        self.fs = float(fs)
        self.clock = clock
        self.axis_zero = float(axis_zero)
        self.cache_tag = cache_tag
        self.half = config.WINDOW_SEC / 2.0
        self.freqs = np.asarray(config.TFR_FREQS, dtype=float)
        self.n_cycles = np.clip(self.freqs / 2.0, *config.TFR_N_CYCLES_RANGE)
        self.out_fs = float(config.TFR_FS)
        self.df = float(self.freqs[1] - self.freqs[0]) if len(self.freqs) > 1 else 1.0

        self._cache = {}                        # 通道名 -> (n_freqs, n_t) dB
        self._tfr = None
        self.channel = None

        self.plot = pg.PlotWidget()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.plot)

        pi = self.plot.getPlotItem()
        pi.setMouseEnabled(False, False)
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.getAxis("left").setWidth(config.AXIS_WIDTH)
        pi.setLabel("bottom", "时间 (s)")
        pi.setYRange(self.freqs[0] - self.df / 2, self.freqs[-1] + self.df / 2, padding=0)

        self.img = pg.ImageItem()
        self.img.setLookupTable(jet_lut())
        self.img.setLevels(config.TFR_DB_RANGE)
        pi.addItem(self.img)

        self.playhead = pg.InfiniteLine(pos=0, angle=90, movable=False,
                                        pen=pg.mkPen("k", width=1.5))
        pi.addItem(self.playhead)

        if channel not in self.names:
            channel = self.names[0]
        self.set_channel(channel)
        clock.timeChanged.connect(self.update_view)

    # ---- 对外接口 ----
    def set_channel(self, name):
        name = name.strip()
        if name not in self.names:
            return
        self.channel = name
        self._tfr = self._get_tfr(name)
        self.plot.getPlotItem().setLabel("left", f"{name} (Hz)")
        self.update_view(self.clock.time)

    # ---- 计算 / 缓存 ----
    def _cache_file(self, name):
        key = f"{self.freqs[0]}_{self.freqs[-1]}_{len(self.freqs)}_{self.out_fs}_" \
              f"{self.n_cycles.sum():.3f}_{self.data.shape[1]}_{self.fs}"
        h = hashlib.md5(key.encode()).hexdigest()[:8]
        return config.CACHE_DIR / f"tfr_{self.cache_tag}_{name}_{h}.npy"

    def _get_tfr(self, name):
        if name in self._cache:
            return self._cache[name]
        f = self._cache_file(name)
        if f.exists():
            tfr = np.load(f)
        else:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            try:
                self.plot.getPlotItem().setLabel("left", f"{name} 计算中…")
                QtWidgets.QApplication.processEvents()
                ch = self.names.index(name)
                tfr = compute_tfr_db(self.data[ch], self.fs, self.freqs,
                                     self.n_cycles, self.out_fs)
                config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
                np.save(f, tfr)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
        self._cache[name] = tfr
        return tfr

    # ---- 绘制 ----
    def update_view(self, t):
        tz = t - self.axis_zero
        self.plot.getPlotItem().setXRange(tz - self.half, tz + self.half, padding=0)
        self.playhead.setPos(tz)
        if self._tfr is None:
            return

        nt = self._tfr.shape[1]
        k0 = max(int(np.floor((t - self.half) * self.out_fs)) - 1, 0)
        k1 = min(int(np.ceil((t + self.half) * self.out_fs)) + 2, nt)
        if k1 - k0 < 2:
            self.img.clear()
            return

        seg = self._tfr[:, k0:k1]                       # (n_freqs, n_cols)
        self.img.setImage(seg.T, autoLevels=False, levels=config.TFR_DB_RANGE)
        x0 = (k0 - 0.5) / self.out_fs - self.axis_zero
        self.img.setRect(QtCore.QRectF(x0, self.freqs[0] - self.df / 2,
                                       (k1 - k0) / self.out_fs, len(self.freqs) * self.df))