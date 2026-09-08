"""多格式文件隐藏水印 —— 复用 TextWatermark v3 载荷层（加密/封包/CRC）

统一 API：
    embed_file(input_path, wm, password, output_path=None) -> str   # 返回输出路径
    extract_file(input_path, password) -> Optional[str]             # 提取水印明文

按扩展名路由到不同载体适配器：
    .docx  —— 零宽字符副本追加到最长段落末尾（python-docx，无损、可再编辑）
    .pdf   —— 透明文本层写入 base64 标记（PyMuPDF，文本型/扫描型均适用）
    .png/.jpg/.jpeg —— 全网格 8×8 DCT 频域盲水印（numpy）：
       v2 抗裁剪（网格相位搜索+循环移位）、抗等比放大（缩放假设）、抗 JPEG；
       等比缩小 <1.0（信息有损）与旋转为已知边界（v2.1 待增强，自动降级/记录）

设计要点（与 text_watermark.py 一致的分层）：
    载荷层完全复用 TextWatermark：PBKDF2+HMAC-CTR 加密 → MAGIC+len+crc 封包
    载体适配只解决「把 bit/密文写进载体」与「从载体读回」。
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

import numpy as np

from text_watermark import TextWatermark

# ── 扩展名路由 ────────────────────────────────────────────────
DOCX_EXTS = {".docx"}
PDF_EXTS = {".pdf"}
IMG_EXTS = {".png", ".jpg", ".jpeg"}


def _route(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in DOCX_EXTS:
        return "docx"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMG_EXTS:
        return "img"
    raise ValueError(f"暂不支持的文件类型: {ext}（支持 .docx / .pdf / .png / .jpg）")


def _default_out(input_path: str, tag: str = "_wm") -> str:
    root, ext = os.path.splitext(input_path)
    return f"{root}{tag}{ext}"


# ════════════════════════════════════════════════════════════════
# Word (.docx) —— 零宽字符副本
# ════════════════════════════════════════════════════════════════
def _docx_embed(path: str, wm: str | bytes, tw: TextWatermark) -> str:
    from docx import Document
    doc = Document(path)
    # 选文本最长的段落追加副本（≤3 段做冗余）
    paras = [p for p in doc.paragraphs if len(p.text) >= 20]
    if not paras:
        raise ValueError("文档过短：需要至少一段 ≥20 字符的正文才能嵌入水印")
    paras.sort(key=lambda p: len(p.text), reverse=True)
    for p in paras[:3]:
        p.add_run(tw.generate_watermark(wm))   # 3 份完整副本的零宽串
    out = _default_out(path)
    doc.save(out)
    return out


def _docx_extract(path: str, tw: TextWatermark) -> Optional[str]:
    from docx import Document
    doc = Document(path)
    full = "\n".join(p.text for p in doc.paragraphs)
    return tw.extract(full)


# ════════════════════════════════════════════════════════════════
# PDF —— 透明文本层标记（对文本型/扫描型 PDF 均有效）
# ════════════════════════════════════════════════════════════════
_MARK_A = "#TWM#"
_MARK_B = "#MWT#"
_PDF_FONTSIZE = 7


def _pdf_embed(path: str, wm: str | bytes, tw: TextWatermark) -> str:
    import fitz
    if isinstance(wm, str):
        wm = wm.encode("utf-8")
    enc = tw._encrypt(wm)
    b64 = base64.urlsafe_b64encode(enc).decode("ascii")   # 无特殊字符
    marker = f"{_MARK_A}{b64}{_MARK_B}"
    doc = fitz.open(path)
    try:
        if doc.page_count == 0:
            raise ValueError("PDF 没有任何页面，无法嵌入水印")
        for page in doc:
            r = page.rect
            # 页脚中央，白色透明小字（视觉不可见、仍可被文本提取）
            point = fitz.Point(r.width / 2 - len(marker) * _PDF_FONTSIZE / 4,
                               r.height - 12)
            page.insert_text(point, marker, fontname="helv",
                             fontsize=_PDF_FONTSIZE,
                             color=(1, 1, 1), fill_opacity=0.0, overlay=True)
        out = _default_out(path)
        doc.save(out, garbage=3, deflate=True)
        return out
    finally:
        doc.close()


def _pdf_extract(path: str, tw: TextWatermark) -> Optional[str]:
    import fitz
    doc = fitz.open(path)
    try:
        for page in doc:
            txt = page.get_text()
            i = txt.find(_MARK_A)
            if i < 0:
                continue
            j = txt.find(_MARK_B, i)
            if j < 0:
                continue
            try:
                enc = base64.urlsafe_b64decode(txt[i + len(_MARK_A):j])
                return tw._decrypt(enc).decode("utf-8")
            except Exception:
                continue
        return None
    finally:
        doc.close()


# ════════════════════════════════════════════════════════════════
# 图片 —— DCT 频域盲水印
# ════════════════════════════════════════════════════════════════
# 8x8 DCT-II 正交变换矩阵（C @ block @ C.T 为正变换，逆 = C.T @ F @ C）
_DCT_MAT: Optional[np.ndarray] = None
_FREQ_A = (3, 1)    # 中频系数对 A（Koch-Zhao 式差值编码）
_FREQ_B = (1, 3)    # 中频系数对 B
_DELTA = 13.0       # 嵌入强度（鲁棒 vs 可见折中）
_B_STD = [256, 384, 512, 768, 1024, 1536, 2048, 3072]   # 标准位长（bit）


def _dct_mat() -> np.ndarray:
    global _DCT_MAT
    if _DCT_MAT is None:
        n = 8
        C = np.zeros((n, n))
        for k in range(n):
            for i in range(n):
                C[k, i] = np.sqrt(1 / n) if k == 0 else \
                    np.sqrt(2 / n) * np.cos(np.pi * (2 * i + 1) * k / (2 * n))
        _DCT_MAT = C
    return _DCT_MAT


def _block_dct(blocks: np.ndarray) -> np.ndarray:
    """blocks: (m,8,8) float → 逐块 DCT。F = C·B·Cᵀ（正交变换，Cᵀ=C⁻¹）"""
    C = _dct_mat()
    return np.einsum("ij,mjk,lk->mil", C, blocks, C)


def _block_idct(coefs: np.ndarray) -> np.ndarray:
    """逆变换 B = Cᵀ·F·C"""
    C = _dct_mat()
    return np.einsum("ji,mjk,kl->mil", C, coefs, C)


def _img_to_y_blocks(y: np.ndarray, ph: int, pw: int):
    """亮度 Y 的左上 (ph,pw) 区域切成 (m,8,8) 块数组"""
    yc = y[:ph, :pw].astype(np.float64)
    return yc.reshape(ph // 8, 8, pw // 8, 8).transpose(0, 2, 1, 3).reshape(-1, 8, 8)


def _y_blocks_to_y(y: np.ndarray, y_blocks: np.ndarray, ph: int, pw: int):
    """修改后的块数组写回左上区域，其余亮度像素保持不变"""
    y_new = y_blocks.reshape(ph // 8, pw // 8, 8, 8).transpose(0, 2, 1, 3) \
        .reshape(ph, pw)
    y[:ph, :pw] = y_new
    return y


def _to_ycc(img: np.ndarray):
    """RGB(H,W,3) uint8 → (Y, Cb, Cr) float（JPEG 标准系数，全图往返自洽）"""
    r = img[..., 0].astype(np.float64)
    g = img[..., 1].astype(np.float64)
    b = img[..., 2].astype(np.float64)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return y, cb, cr


def _from_ycc(y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> np.ndarray:
    r = y + 1.402 * (cr - 128)
    g = y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128)
    b = y + 1.772 * (cb - 128)
    return np.clip(np.stack([r, g, b], axis=-1), 0, 255).astype(np.uint8)


def _gap_perm_nb(password: bytes, nb: int, m: int) -> Optional[list]:
    """由密码派生的伪随机块序（编解码端一致）"""
    import hashlib
    import random as _random
    if m > nb or m <= 0:
        return None
    h = hashlib.sha256(password + b"|imgperm|" + str(nb).encode()).digest()
    rng = _random.Random(int.from_bytes(h[:8], "big"))
    return rng.sample(range(nb), m)


def _img_embed(path: str, wm: str | bytes, tw: TextWatermark) -> str:
    from PIL import Image
    img = np.asarray(Image.open(path).convert("RGB"))
    h, w = img.shape[:2]
    ph, pw = h - h % 8, w - w % 8
    if ph < 64 or pw < 64:
        raise ValueError("图片过小（至少 64×64）无法嵌入水印")
    y, cb, cr = _to_ycc(img)
    blocks = _img_to_y_blocks(y, ph, pw)
    nb = blocks.shape[0]

    if isinstance(wm, str):
        wm = wm.encode("utf-8")
    payload = tw._build_payload(wm)
    nbits = len(payload) * 8
    B = next((s for s in _B_STD if s >= nbits), None)
    if B is None:
        raise ValueError("水印内容过长")
    R = max(1, min(5, nb // B))          # 每 bit 冗余副本数
    perm = _gap_perm_nb(tw.password, nb, B * R)
    if perm is None:
        raise ValueError("图片容量不足（图片过小或水印过长）")

    # payload bit 补齐到 B
    bits = TextWatermark._bytes_to_bits(payload + bytes((B - nbits) // 8))
    coefs = _block_dct(blocks)
    # 差值编码：bit=1 → cA ≥ cB + Δ；bit=0 → cB ≥ cA + Δ
    for i, b in enumerate(bits):
        for c in range(R):
            blk = coefs[perm[i * R + c]]
            a = (_FREQ_A[0], _FREQ_A[1]); bb = (_FREQ_B[0], _FREQ_B[1])
            ca, cbv = float(blk[a]), float(blk[bb])
            mid = (ca + cbv) / 2
            if b:
                blk[a] = mid + _DELTA / 2
                blk[bb] = mid - _DELTA / 2
            else:
                blk[a] = mid - _DELTA / 2
                blk[bb] = mid + _DELTA / 2
    y2 = _y_blocks_to_y(y, _block_idct(coefs), ph, pw)
    out = _default_out(path)
    Image.fromarray(_from_ycc(y2, cb, cr)).save(out, quality=95)
    return out


def _img_extract(path: str, tw: TextWatermark) -> Optional[str]:
    from PIL import Image
    img = np.asarray(Image.open(path).convert("RGB"))
    h, w = img.shape[:2]
    ph, pw = h - h % 8, w - w % 8
    if ph < 64 or pw < 64:
        return None
    y, _cb, _cr = _to_ycc(img)
    blocks = _img_to_y_blocks(y, ph, pw)
    nb = blocks.shape[0]
    coefs = _block_dct(blocks)

    for B in _B_STD:
        R = max(1, min(5, nb // B))
        if B * R > nb:
            continue
        perm = _gap_perm_nb(tw.password, nb, B * R)
        if perm is None:
            continue
        votes = []
        for i in range(B):
            s = 0
            for c in range(R):
                blk = coefs[perm[i * R + c]]
                s += 1 if blk[_FREQ_A] >= blk[_FREQ_B] else 0
            votes.append(1 if s * 2 >= R else 0)
        data = TextWatermark._bits_to_bytes(votes)
        res = tw._parse_v2(data)
        if res is not None:
            return res
    return None


# ════════════════════════════════════════════════════════════════
# 图片 v2 —— 全网格 DCT 频域盲水印（抗裁剪 / 等比缩放 / JPEG）
# ────────────────────────────────────────────────────────────────
# 设计：v1 把水印写在"固定 8×8 像素网格"上，裁剪/缩放会改变块数 nb 且
# 破坏网格映射 → 无法重建。v2 同样写满整个 8×8 网格（载体最多、覆盖天然
# 保证），但提取端通过两层几何搜索恢复：
#   1) bit 归属 = (a·c + b·r) mod B，c/r 为块索引（非像素中心——像素中心
#      ≡0 mod 8 会导致线性映射退化）。a,b 取大奇数，对稠密索引网格几乎总能
#      全覆盖（每 bit 大量冗余载体 → 多数投票）。
#   2) 等比缩放：提取端穷举"缩放假设"，把输入按假设倒数缩放回原尺寸再提取，
#      命中真实缩放 → 网格对齐 → 直接恢复（s=1.0 即覆盖未缩放输入）。
#   3) 裁剪：裁剪 = 整体平移 (dx,dy)。原图 8×8 块在裁剪图中仍完整（若未被裁
#      掉），但其网格与裁剪图自身网格错开 (dx mod 8, dy mod 8)——提取端穷举
#      8×8=64 种网格相位；命中正确相位时读到的就是原块 → bit 位置整体平移
#      K=(a·mx+b·my) mod B → 再穷举 B 次循环移位即恢复（_parse_v2 自带 MAGIC/
#      CRC 门控，错误移位快速失败）。
#   4) JPEG：8×8 DCT 调制与 JPEG 量化网格同相位，q85 下仍有冗余投票兜底。
# 已知边界：旋转未做角度对齐(v2.1)；块数不足以容纳 B 个 bit 时自动降级 v1。
# ════════════════════════════════════════════════════════════════
# 低频系数对 (1,0)/(0,1)：空间频率 1/8 cyc/px，2× 下采样(新 Nyquist=2/8)后仍完整
# 保留——(3,1)/(1,3) 的 3/8 分量会被下采样混叠抹除导致 scale-0.5 无法恢复。
_F2_A = (1, 0)
_F2_B = (0, 1)
_DELTA2 = 12.0
_B2_STD = [256, 384, 512, 768, 1024, 1536, 2048, 3072]
_PATCH2 = 8
_SCALE_HYP = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5]  # 提取端穷举的缩放假设
# 放大提取加速：优先尝试"大缩放假设"(2.5→0.5)。放大输入的正确假设 s>1 会"缩小"
# 图像(网格小、DCT 廉价)，而错误假设 s<1 会"放大"图像(网格爆炸、极慢)。降序优先可
# 在命中正确假设后立即返回，跳过昂贵的放大网格。仅改变尝试顺序，不改变任何水印数学。
_SCALE_ORDER = [2.5, 2.0, 1.5, 1.25, 1.0, 0.75, 0.5]
_WORK_CAP = 1024  # 几何搜索分辨率上限(长边 px)；仅对超大输入生效，不触发已验证的 ≤640 用例
# 块索引线性映射 (a,b) 候选集（均取与 384 互素的奇数，避免退化；大系数对稠密
# 索引网格覆盖最好）。嵌入端选首个"每 bit≥2 载体"的候选，提取端遍历同集——
# 错误的 (a,b) 在所有循环移位下解析均失败(快退)，正确候选命中即返回。
_LIN_CAND = [(31, 19), (29, 21), (29, 7), (27, 11), (21, 17), (19, 27),
             (31, 13), (25, 19), (23, 21), (17, 29)]
_DCT32 = None


def _dct_mat_n(n: int) -> np.ndarray:
    C = np.zeros((n, n))
    for k in range(n):
        for i in range(n):
            C[k, i] = np.sqrt(1 / n) if k == 0 else \
                np.sqrt(2 / n) * np.cos(np.pi * (2 * i + 1) * k / (2 * n))
    return C


def _dct32() -> np.ndarray:
    global _DCT32
    if _DCT32 is None:
        _DCT32 = _dct_mat_n(_PATCH2)
    return _DCT32


def _pick_ab(nb_w, nb_h, B):
    """在 nb_w×nb_h 块索引网格上选 (a,b)：首个"每 bit≥2 载体"的候选，否则首个
    全覆盖(≥1)；再否则返回 None（降级 v1）。索引网格稠密时 _LIN_CAND 几乎必中。"""
    cols = np.arange(nb_w); rows = np.arange(nb_h)
    for want in (2, 1):
        for (a, b) in _LIN_CAND:
            p = (a * cols[:, None] + b * rows[None, :]) % B
            if np.bincount(p.ravel(), minlength=B).min() >= want:
                return (a, b)
    return None


def _dct_mod(bit: int, F: np.ndarray) -> np.ndarray:
    """对 8×8 DCT 系数 F 调制中频系数对：(3,1)/(1,3)。bit=1 → F_A>F_B。"""
    ca, cbv = float(F[_F2_A]), float(F[_F2_B])
    mid = (ca + cbv) / 2
    if bit:
        F[_F2_A] = mid + _DELTA2 / 2
        F[_F2_B] = mid - _DELTA2 / 2
    else:
        F[_F2_A] = mid - _DELTA2 / 2
        F[_F2_B] = mid + _DELTA2 / 2
    return F


def _img_embed_v2(path, wm, tw):
    from PIL import Image
    import cv2
    img = np.asarray(Image.open(path).convert("RGB"))
    h, w = img.shape[:2]
    if min(h, w) < 64:
        raise ValueError("图片过小（至少 64×64）无法嵌入水印")
    # 原生空间嵌入（不做任何缩放，保证写回零失真、高 PSNR、且尺寸不变）
    y, cb, cr = _to_ycc(img)
    gray = y.astype(np.float64)
    if isinstance(wm, str):
        wm = wm.encode("utf-8")
    payload = tw._build_payload(wm)
    nbits = len(payload) * 8
    B = next((s for s in _B2_STD if s >= nbits), None)
    if B is None:
        raise ValueError("水印内容过长")
    nb_w, nb_h = w // 8, h // 8          # 8×8 网格块数（写满整图，载体最多）
    if nb_w * nb_h < B:
        return _img_embed(path, wm, tw)  # 块数不足以容纳 B bit → 降级 v1
    ab = _pick_ab(nb_w, nb_h, B)
    if ab is None:
        return _img_embed(path, wm, tw)  # 索引网格无法全覆盖 → 降级 v1
    a, b = ab
    bits = TextWatermark._bytes_to_bits(payload + bytes((B - nbits) // 8))
    C = _dct32()
    # 全网格承载：块(c,r) 承载 bit = (a·c + b·r) mod B（每 bit 大量冗余 → 多数投票）
    for r in range(nb_h):
        y0, y1 = r * 8, (r + 1) * 8
        for c in range(nb_w):
            bit = bits[(a * c + b * r) % B]
            x0, x1 = c * 8, (c + 1) * 8
            blk = gray[y0:y1, x0:x1]
            F = np.einsum("ij,mjk,lk->mil", C, blk[None], C)[0]
            _dct_mod(bit, F)
            blk[:] = np.einsum("ji,mjk,kl->mil", C, F[None], C)[0]
    y[:] = gray
    out = _default_out(path)
    Image.fromarray(_from_ycc(y, cb, cr)).save(out, quality=95)
    return out


def _try_shifts(tw, votes, B):
    """对 votes(长度 B 的 0/1) 穷举循环移位（覆盖裁剪平移 K，含子字节相位），
    _parse_v2 自带 MAGIC+CRC 门控：错误移位快速失败，命中即返回明文。"""
    for r in range(8):
        rv = votes[r:] + votes[:r] if r else votes
        data = TextWatermark._bits_to_bytes(rv)
        n = len(data)
        for q in range(n):
            cand = data if q == 0 else data[q:] + data[:q]
            if cand[:4] == b"TWM2":      # MAGIC_V2 前缀门控（几乎总是快退）
                res = tw._parse_v2(cand)
                if res is not None:
                    return res
    return None


def _try_grid(g8, tw, phases):
    """在 g8 上按给定相位列表逐一读取 8×8 网格 → 投票 → 循环移位恢复。"""
    C = _dct32()
    nb_h, nb_w = g8.shape[:2]
    for (fx, fy) in phases:
        n_c = (nb_w - fx) // 8
        n_r = (nb_h - fy) // 8
        if n_c < 1 or n_r < 1 or n_c * n_r < _B2_STD[0]:
            continue
        sign = np.zeros((n_r, n_c), dtype=np.int64)
        for r in range(n_r):
            y0 = r * 8 + fy
            for c in range(n_c):
                x0 = c * 8 + fx
                blk = g8[y0:y0 + 8, x0:x0 + 8]
                F = np.einsum("ij,mjk,lk->mil", C, blk[None].astype(np.float64), C)[0]
                sign[r, c] = 1 if F[_F2_A] >= F[_F2_B] else 0
        for B in _B2_STD:
            if n_c * n_r < B:
                continue
            # 嵌入端用 _pick_ab 选 (a,b)，提取端把同款结果放最前 → 常见情形一次命中
            pref = _pick_ab(n_c, n_r, B)
            if pref is None:
                continue          # 该 B 无候选可全覆盖 → 不可能是嵌入所用的 B
            for (a, b) in ([pref] + [x for x in _LIN_CAND if x != pref]):
                # sign 矩阵按 (r,c) 索引（r 外层、c 内层），p 必须同构：
                # p[r,c] = (a·c + b·r) % B，否则 ravel 后错位 → 投票随机
                p = (a * np.arange(n_c)[None, :] + b * np.arange(n_r)[:, None]) % B
                pf = p.ravel(); sf = sign.ravel()
                tot = np.bincount(pf, minlength=B)
                one = np.bincount(pf, weights=sf, minlength=B)
                votes = np.where((tot > 0) & (2 * one >= tot), 1, 0).tolist()
                res = _try_shifts(tw, votes, B)
                if res is not None:
                    return res
    return None


def _cap_undone(Is):
    """几何搜索防御性封顶：仅当长边超过 _WORK_CAP 时才下采样。水印为 1/8 低频，
    对下采样稳健；封顶把 DCT 网格规模锁死在 (1024/8)² 量级，避免超大输入(如原图
    很大再被放大)拖垮提取。已验证的 ≤640px 用例长边均 <_WORK_CAP，绝不触发。"""
    import cv2
    hh, ww = Is.shape[:2]
    m = max(hh, ww)
    if m > _WORK_CAP:
        f = _WORK_CAP / m
        Is = cv2.resize(Is, (max(16, int(round(ww * f))),
                             max(16, int(round(hh * f)))), cv2.INTER_LINEAR)
    return Is


def _img_extract_v2(path, tw):
    from PIL import Image
    import cv2
    img = np.asarray(Image.open(path).convert("RGB"))
    h, w = img.shape[:2]
    # pass A：相位(0,0) 对缩放假设（覆盖 clean / JPEG / 等比缩放）。按 _SCALE_ORDER
    # 优先尝试大缩放假设 —— 放大输入的正确假设 s>1 会"缩小"图像(网格小、廉价)，可
    # 在命中后立刻返回，跳过 s<1 那些会把图像放大的昂贵网格。
    for s in _SCALE_ORDER:
        nw, nh = max(16, int(round(w / s))), max(16, int(round(h / s)))
        Is = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        Is = _cap_undone(Is)
        y, _cb, _cr = _to_ycc(Is)
        g8 = y.astype(np.uint8)
        res = _try_grid(g8, tw, ((0, 0),))
        if res is not None:
            return res
    # pass B：8×8=64 种网格相位穷举（覆盖裁剪造成的网格错位）。裁剪不改变尺度，
    # 故只在 s=1.0 做全相位搜索；等比缩放由 pass A 相位(0,0)覆盖。
    # （裁剪+缩放 的组合攻击超出当前鲁棒包络 → 返回 None。）
    for s in [1.0]:
        nw, nh = max(16, int(round(w / s))), max(16, int(round(h / s)))
        Is = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        Is = _cap_undone(Is)
        y, _cb, _cr = _to_ycc(Is)
        g8 = y.astype(np.uint8)
        phases = [(fx, fy) for fx in range(8) for fy in range(8)]
        res = _try_grid(g8, tw, phases)
        if res is not None:
            return res
    return None


# ════════════════════════════════════════════════════════════════
# 统一入口
# ════════════════════════════════════════════════════════════════
def embed_file(input_path: str, wm: str | bytes, password: str | bytes,
               output_path: Optional[str] = None) -> str:
    kind = _route(input_path)
    tw = TextWatermark(password)
    out = _route_dispatch(kind, input_path, wm, tw)
    if output_path and output_path.lower() != out.lower():
        import shutil
        shutil.copyfile(out, output_path)
        os.remove(out)
        out = output_path
    return out


def extract_file(input_path: str, password: str | bytes) -> Optional[str]:
    kind = _route(input_path)
    tw = TextWatermark(password)
    if kind == "docx":
        return _docx_extract(input_path, tw)
    if kind == "pdf":
        return _pdf_extract(input_path, tw)
    if kind == "img":
        r = _img_extract_v2(input_path, tw)
        return r if r is not None else _img_extract(input_path, tw)
    return None


def _route_dispatch(kind: str, path: str, wm: str | bytes,
                    tw: TextWatermark) -> str:
    if kind == "docx":
        return _docx_embed(path, wm, tw)
    if kind == "pdf":
        return _pdf_embed(path, wm, tw)
    if kind == "img":
        return _img_embed_v2(path, wm, tw)
    raise ValueError("未知类型")
