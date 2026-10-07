"""可编辑的 Involvement 分段模型。内部时间统一用 EEG 时间（秒）。"""
import numpy as np
import pandas as pd
from pyqtgraph.Qt import QtCore


class InvolvementModel(QtCore.QObject):
    changed = QtCore.Signal()          # 分段变化 → 面板重绘
    dirtyChanged = QtCore.Signal(bool)  # 未导出的修改状态

    def __init__(self, df, t0, parent=None):
        """df: 原始 involvement 表（可为 None）；t0: sample_start 在 EEG 时间轴上的位置。"""
        super().__init__(parent)
        self.t0 = float(t0)
        self.ss_onset = 0.0
        self.columns = ["Onset", "Duration", "Annotation", "Involvement"]
        self.others = pd.DataFrame(columns=self.columns)   # sample_start 等非分段行，原样保留
        self.segs = []                  # [(s, e, label, meta_dict)]
        self._undo = []
        self.dirty = False

        need = {"Onset", "Duration", "Annotation", "Involvement"}
        if df is None:
            return
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        if not need.issubset(df.columns):
            print(f"[动作类型] 缺少列 {need - set(df.columns)}")
            return
        self.columns = list(df.columns)

        ann = df["Annotation"].astype(str).str.strip().str.lower()
        is_ss = ann == "sample_start"
        if is_ss.any():
            self.ss_onset = float(df.loc[is_ss, "Onset"].iloc[0])
        onset = pd.to_numeric(df["Onset"], errors="coerce")
        dur = pd.to_numeric(df["Duration"], errors="coerce")
        is_seg = ~is_ss & df["Involvement"].notna() & onset.notna() & dur.notna()

        self.others = df[~is_seg].copy()
        for idx in df.index[is_seg]:
            meta = df.loc[idx].drop(["Onset", "Duration", "Involvement"]).to_dict()
            s = self.t0 + float(onset[idx]) - self.ss_onset
            self.segs.append((s, s + float(dur[idx]), str(df.at[idx, "Involvement"]).strip(), meta))
        self.segs.sort(key=lambda x: x[0])

    # ---- 读取 ----
    def arrays(self):
        s = np.array([x[0] for x in self.segs], dtype=float)
        e = np.array([x[1] for x in self.segs], dtype=float)
        return s, e, [x[2] for x in self.segs]

    @property
    def can_undo(self):
        return bool(self._undo)

    # ---- 编辑 ----
    def assign(self, t0, t1, label):
        """把 [t0, t1] 区间设为 label：与之重叠的旧分段被裁剪/切开，新区间覆盖其上。"""
        if t1 - t0 <= 0:
            return
        self._undo.append(list(self.segs))
        out = []
        for s, e, l, meta in self.segs:
            if e <= t0 or s >= t1:
                out.append((s, e, l, meta))
                continue
            if s < t0:
                out.append((s, t0, l, meta))
            if e > t1:
                out.append((t1, e, l, meta))
        out.append((t0, t1, label, {"Annotation": "manual_edit"}))
        out.sort(key=lambda x: x[0])
        self.segs = out
        self._set_dirty(True)
        self.changed.emit()

    def undo(self):
        if self._undo:
            self.segs = self._undo.pop()
            self._set_dirty(True)
            self.changed.emit()

    def _set_dirty(self, v):
        if self.dirty != v:
            self.dirty = v
            self.dirtyChanged.emit(v)

    # ---- 导出 ----
    def to_dataframe(self):
        rows = []
        for s, e, l, meta in self.segs:
            r = dict(meta)
            r["Onset"] = round(s - self.t0 + self.ss_onset, 6)
            r["Duration"] = round(e - s, 6)
            r["Involvement"] = l
            rows.append(r)
        seg_df = pd.DataFrame(rows, columns=self.columns)
        parts = [d for d in (self.others, seg_df) if len(d)]
        df = pd.concat(parts, ignore_index=True) if parts else seg_df
        df["_o"] = pd.to_numeric(df["Onset"], errors="coerce")
        df = df.sort_values("_o", kind="stable", na_position="last").drop(columns="_o")
        return df[self.columns]

    def export(self, path):
        self.to_dataframe().to_excel(path, index=False)
        self._set_dirty(False)