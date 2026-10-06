"""视频面板：跟随主时钟显示对应帧。播放时顺序解码，拖动/跳转时随机 seek。"""
import math

import cv2
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import config

class VideoPanel(QtWidgets.QWidget):
    def __init__(self, path, clock, t_offset=0.0, parent=None):
        super().__init__(parent)
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise OSError(f"无法打开视频: {path}")
        self.clock = clock
        self.t_offset = float(t_offset)          # 视频 0 秒对应的 EEG 时间
        self.vw = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.vh = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.n_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.aspect = self.vw / self.vh

        self._last = -1
        self._img = None
        self._buf = None                         # 保持 numpy 缓冲区存活，供 QImage 引用

        # 忽略 sizeHint，宽高完全由布局的 stretch 决定
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                           QtWidgets.QSizePolicy.Policy.Ignored)
        clock.timeChanged.connect(self.update_view)
        self.update_view(clock.time)

    @property
    def duration(self):
        return self.n_frames / self.fps

    def update_view(self, t):
        idx = int(math.floor((t - self.t_offset) * self.fps + 1e-6))
        if idx < 0 or idx >= self.n_frames:      # 视频覆盖范围之外：显示黑屏
            if self._img is not None:
                self._img, self._last = None, -1
                self.update()
            return
        if idx == self._last:
            return

        gap = idx - self._last
        if self._last >= 0 and 0 < gap <= config.VIDEO_MAX_SKIP:
            for _ in range(gap - 1):             # 倍速播放：跳过中间帧
                self.cap.grab()
        else:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self.cap.read()
        if not ok:
            self._last = -1
            return
        self._last = idx
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        self._buf = rgb
        self._img = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888)
        self.update()

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0))
        if self._img is None:
            return
        W, H = self.width(), self.height()
        s = min(W / self._img.width(), H / self._img.height())     # 保持宽高比，居中
        w, h = self._img.width() * s, self._img.height() * s
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QtCore.QRectF((W - w) / 2, (H - h) / 2, w, h), self._img)

    def release(self):
        self.cap.release()