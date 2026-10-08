"""由 ICA 成分的通道权重 + 通道色卡，给每个成分算一个代表色。"""
import numpy as np
from mne.preprocessing import read_ica


def compute_ica_colors(fif_path, ica_names, ch_colors,
                       power=2.0, gamma=2.2, boost=1.3):
    """
    fif_path  : ICA 的 .fif 文件
    ica_names : bdf 里 ICA 通道名（按顺序，第 i 个对应第 i 个成分）
    ch_colors : {通道名: (R,G,B) 0~255}，即 load_colors(CHANNEL_CMAP_PATH)
    返回 (colors, labels)：
      colors {原成分名: (R,G,B)}，labels {原成分名: 带半球标记的显示名}
    """
    ica = read_ica(str(fif_path), verbose="ERROR")
    A = ica.get_components()                          # (n_channels, n_components)
    ch_names = [c.strip() for c in ica.ch_names]
    n_comp = A.shape[1]

    if len(ica_names) != n_comp:
        print(f"[ICA] 警告：bdf 中有 {len(ica_names)} 个 ICA 通道，"
              f"fif 中有 {n_comp} 个成分，只按顺序匹配前 {min(len(ica_names), n_comp)} 个")

    idx = [i for i, c in enumerate(ch_names) if c in ch_colors]
    if not idx:
        print("[ICA] fif 中的通道名与色卡无交集，请检查通道名")
        return {}, {}
    chs = [ch_names[i] for i in idx]
    C = np.array([ch_colors[c] for c in chs], dtype=float) / 255.0
    Cl = C ** gamma                                   # 线性空间
    is_L = np.array([c.upper().startswith("L") for c in chs])

    colors, labels = {}, {}
    for k, name in enumerate(ica_names[:n_comp]):
        w = np.abs(A[idx, k]) ** power
        if not np.isfinite(w).all() or w.sum() <= 0:
            continue
        w = w / w.sum()

        rgb = (w @ Cl) ** (1.0 / gamma)               # 加权平均色
        gray = rgb.mean()
        rgb = np.clip(gray + boost * (rgb - gray), 0, 1)   # 拉开饱和度
        n = name.strip()
        colors[n] = tuple(int(round(255 * v)) for v in rgb)

        labels[n] = f"{n}"
    return colors, labels