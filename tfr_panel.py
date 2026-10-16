"""时频面板：显示当前 WINDOW_SEC 窗口内单个通道的 TFR（dB），播放头固定在正中。

整段数据对选定通道只计算一次（Morlet 小波，分块 + 降采样），之后每帧只切片显示。
功率单位：数据 µV 先转为 V，再 10*log10(V^2)。
纵轴为对数频率轴：TFR 本身仍按线性频率计算，显示时重采样到对数均匀的行上。
"""
import hashlib

import numpy as np
import pyqtgraph as pg
from mne.time_frequency import tfr_array_morlet
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import config

# 纵轴刻度（Hz）与对数显示的行数
FREQ_TICKS = (1, 4, 8, 13, 30, 80, 150)
N_LOG_ROWS = 200
FREQ_OFFSET = 10.0

class TimeAxis(pg.AxisItem):
    """offset 为 None 时按样本相对时间显示；否则按 mm:ss 显示视频时间。双击轴标签触发回调。"""
    offset = None
    on_double_click = None

    def tickStrings(self, values, scale, spacing):
        if self.offset is None:
            return super().tickStrings(values, scale, spacing)
        out = []
        for v in values:
            sec = int(round(v + self.offset))
            m, s = divmod(abs(sec), 60)
            out.append(f"{'-' if sec < 0 else ''}{m:02d}:{s:02d}")
        return out

    def mouseClickEvent(self, ev):
        if (ev.button() == QtCore.Qt.MouseButton.LeftButton and ev.double()
                and self.on_double_click is not None
                and self.label.sceneBoundingRect().contains(ev.scenePos())):
            self.on_double_click()
            ev.accept()
            return
        super().mouseClickEvent(ev)




class SmoothImageItem(pg.ImageItem):
    """绘制时启用平滑插值（类似 gouraud shading）。"""

    def paint(self, p, *args):
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        super().paint(p, *args)

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
                 channel=None, video_t0=None, parent=None):
        super().__init__(parent)
        self.data = data
        self.names = [n.strip() for n in names]
        self.fs = float(fs)
        self.clock = clock
        self.axis_zero = float(axis_zero)
        self.video_t0 = video_t0
        self.video_mode = False        
        self.cache_tag = cache_tag
        self.half = config.WINDOW_SEC / 2.0
        self.freqs = np.asarray(config.TFR_FREQS, dtype=float)
        self.n_cycles = np.clip(self.freqs / 2.0, *config.TFR_N_CYCLES_RANGE)
        self.out_fs = float(config.TFR_FS)
        self.df = float(self.freqs[1] - self.freqs[0]) if len(self.freqs) > 1 else 1.0

        # ---- 对数频率轴：线性频率行 → 对数均匀行的插值矩阵 ----
        self.f_lo = max(float(self.freqs[0] - self.df / 2), 1e-3)   # 图像下沿 (Hz)
        self.f_hi = float(self.freqs[-1] + self.df / 2)             # 图像上沿 (Hz)
        self.log_lo, self.log_hi = np.log10(self.f_lo + FREQ_OFFSET), np.log10(self.f_hi + FREQ_OFFSET)        
        step = (self.log_hi - self.log_lo) / N_LOG_ROWS
        centers = 10.0 ** (self.log_lo + (np.arange(N_LOG_ROWS) + 0.5) * step) - FREQ_OFFSET
        self._W = self._interp_matrix(self.freqs, centers)          # (N_LOG_ROWS, n_freqs)

        self._cache = {}                        # 通道名 -> (n_freqs, n_t) dB
        self._tfr = None
        self.channel = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.title = QtWidgets.QLabel()
        self.title.setStyleSheet("font-size: 9px;")
        self.title.setContentsMargins(config.AXIS_WIDTH, 0, 0, 0)
        lay.addWidget(self.title)

        self.time_axis = TimeAxis("bottom")
        self.time_axis.on_double_click = self.toggle_time_mode
        self.plot = pg.PlotWidget(axisItems={"bottom": self.time_axis})
        self.plot.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)        
        lay.addWidget(self.plot, 1)

        pi = self.plot.getPlotItem()
        pi.setMouseEnabled(False, False)
        pi.setMenuEnabled(False)
        pi.hideButtons()
        font = QtGui.QFont()
        font.setPointSize(5)                      # 与脑电通道名一致
        for side in ("left", "bottom"):
            pi.getAxis(side).setStyle(tickFont=font)
        left = pi.getAxis("left")
        left.setWidth(config.AXIS_WIDTH)
        left.setTicks([[(float(np.log10(v + FREQ_OFFSET)), f"{v:g}") for v in FREQ_TICKS]])
        pi.setLabel("bottom", "样本相对时间 (s)")
        pi.setLabel("left", "Frequency (Hz)")
        # y 轴坐标 = log10(频率)；范围覆盖所有刻度
        y_lo = min(self.log_lo, np.log10(min(FREQ_TICKS) + FREQ_OFFSET))
        y_hi = max(self.log_hi, np.log10(max(FREQ_TICKS) + FREQ_OFFSET)) + 0.05
        pi.setYRange(y_lo, y_hi, padding=0)

        self.img = SmoothImageItem()
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

    @staticmethod
    def _interp_matrix(freqs, targets):
        """线性插值矩阵 W：W @ x(freqs) ≈ x(targets)，目标频率超出范围时取端点值。"""
        W = np.zeros((len(targets), len(freqs)), dtype=np.float32)
        for j, f in enumerate(targets):
            k = int(np.searchsorted(freqs, f))
            if k <= 0:
                W[j, 0] = 1.0
            elif k >= len(freqs):
                W[j, -1] = 1.0
            else:
                w = (f - freqs[k - 1]) / (freqs[k] - freqs[k - 1])
                W[j, k - 1], W[j, k] = 1.0 - w, w
        return W

    def toggle_time_mode(self):
        if self.video_t0 is None:
            return
        self.video_mode = not self.video_mode
        self.time_axis.offset = (self.axis_zero - self.video_t0) if self.video_mode else None
        self.plot.getPlotItem().setLabel(
            "bottom", "视频时间 (mm:ss)" if self.video_mode else "样本相对时间 (s)")
        self.time_axis.picture = None
        self.time_axis.update()    

    # ---- 对外接口 ----
    def set_channel(self, name):
        name = name.strip()
        if name not in self.names:
            return
        self.channel = name
        self.title.setText(f"TFR channel: <b>{name}</b>")
        self._tfr = self._get_tfr(name)
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
                self.title.setText(f"TFR channel: <b>{name}</b> (计算中…)")
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
        seg_log = self._W @ seg                         # (N_LOG_ROWS, n_cols)，行按对数频率均匀排列
        self.img.setImage(seg_log.T, autoLevels=False, levels=config.TFR_DB_RANGE)
        x0 = (k0 - 0.5) / self.out_fs - self.axis_zero
        self.img.setRect(QtCore.QRectF(x0, self.log_lo,
                                       (k1 - k0) / self.out_fs, self.log_hi - self.log_lo))