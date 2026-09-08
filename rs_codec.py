"""
Reed-Solomon 纠删码（GF(2^8)）—— 零依赖实现

编码方式：多项式求值（Polynomial Evaluation）形式
    数据符号 d_0..d_{k-1} 视为多项式 D(x) = Σ d_i · x^i 的系数，
    码字第 j 个符号 = D(α^j)，j = 0..n-1。

解码方式：已知擦除位置（erasure decoding）
    擦除 = 已知「哪些符号丢了」但不知道其值。只要幸存符号 ≥ k 个，
    就能通过解范德蒙德线性方程组（GF(2^8) 上高斯消元）唯一恢复数据。
    这是比「纠错」简单得多的情形，且恢复率是 100%（MDS 性质）。

为什么这套够用：
    文本水印场景中，若可见文本未被改动、仅零宽字符被剥离，
    则字符间隙编号保持不变 —— 丢失的是「位置已知的符号」，
    正好是标准擦除模型，不需要复杂的纠错（Berlekamp-Massey 等）。

限制：n ≤ 255（GF(2^8) 非零元素个数）
"""

from typing import List, Optional, Tuple

# ── GF(2^8) 算术 ────────────────────────────────────────────
# 本原多项式 x^8 + x^4 + x^3 + x^2 + 1
PRIM = 0x11D
N_GF = 255          # 非零元素个数，α^255 = 1
_EXP = [0] * 512
_LOG = [0] * 256


def _build_tables() -> None:
    x = 1
    for i in range(N_GF):
        _EXP[i] = x
        _LOG[x] = i
        # x *= α (α = 2)
        x <<= 1
        if x & 0x100:
            x ^= PRIM
        x &= 0xFF
    # 填充尾部便于指数相加时无需取模
    for i in range(N_GF, 512):
        _EXP[i] = _EXP[i - N_GF]


_build_tables()


def gf_mul(a: int, b: int) -> int:
    """GF(2^8) 乘法"""
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def gf_div(a: int, b: int) -> int:
    """GF(2^8) 除法（b 非 0）"""
    if b == 0:
        raise ZeroDivisionError("GF(2^8) division by zero")
    if a == 0:
        return 0
    return _EXP[(_LOG[a] - _LOG[b]) % N_GF]


def gf_inv(a: int) -> int:
    """GF(2^8) 乘法逆元"""
    if a == 0:
        raise ZeroDivisionError("GF(2^8) inverse of zero")
    return _EXP[(N_GF - _LOG[a]) % N_GF]


def gf_pow(a: int, e: int) -> int:
    """GF(2^8) 幂运算"""
    if a == 0:
        return 0
    return _EXP[(_LOG[a] * e) % N_GF]


# ── RS 编码 ─────────────────────────────────────────────────
def rs_encode(data: bytes, n: int) -> bytes:
    """把 k 个数据符号编码为 n 个码字符号（n ≥ k，n ≤ 255）。

    码字[j] = D(α^j)，D 为以 data 为系数的多项式（Horner 求值）。
    """
    k = len(data)
    if k > n:
        raise ValueError(f"数据符号数 {k} 超过码长 {n}")
    if n > N_GF:
        raise ValueError(f"码长 {n} 超过上限 {N_GF}")
    out = bytearray(n)
    for j in range(n):
        x = _EXP[j]                     # α^j
        acc = 0
        # Horner 求值 D(x) = Σ_{i=0}^{k-1} d_i · x^i
        # 必须从最高次系数 d_{k-1} 开始，故用 reversed
        for coeff in reversed(data):
            acc = gf_mul(acc, x) ^ coeff
        out[j] = acc
    return bytes(out)


# ── RS 解码（已知擦除位置）────────────────────────────────────
def rs_decode(symbols: List[Optional[int]], k: int) -> Optional[bytes]:
    """从带擦除（None）的码字中恢复 k 个数据符号 —— 拉格朗日插值，O(k²)。

    symbols: 长度 n 的列表，None 表示该符号被擦除（位置已知）
    返回：恢复出的 k 个数据字节；若幸存符号不足 k 个则返回 None。

    做法：
      已知 k 个点 (x_j, y_j)，其中 x_j = α^pos_j。
      1) 构造 P(x) = Π_m (x - x_m)                     —— O(k²)
      2) 对每个 j，用「综合除法」求 Q_j(x) = P(x)/(x - x_j)  —— O(k)
      3) 分母 d_j = Π_{m≠j}(x_j - x_m)，即 Q_j(x_j)      —— O(k)
      4) D(x) = Σ_j (y_j / d_j) · Q_j(x)，其系数即数据符号
    总复杂度 O(k²)，远优于高斯消元的 O(k³)。
    """
    known: List[Tuple[int, int]] = [
        (pos, val) for pos, val in enumerate(symbols) if val is not None
    ]
    if len(known) < k:
        return None
    known = known[:k]                       # k 个点即可唯一确定多项式
    xs = [_EXP[pos % N_GF] for pos, _ in known]   # x_j = α^pos_j（互异且非零）
    ys = [val for _, val in known]

    # 1) P(x) = Π (x - x_m)，系数按升幂存放，长度 k+1，最高次为 1
    P = [1]
    for a in xs:
        newP = [0] * (len(P) + 1)
        for i, c in enumerate(P):
            newP[i] ^= gf_mul(a, c)         # GF(2^8) 中减法即异或
            newP[i + 1] ^= c                # 乘 x
        P = newP

    desc = P[::-1]                          # desc[t] = x^(k-t) 的系数
    D = [0] * k                             # 结果多项式系数（升幂）

    for j, a in enumerate(xs):
        # 2) 综合除法 Q_j = P / (x - a)，q[t] 为 x^(k-1-t) 的系数
        q = [0] * k
        q[0] = desc[0]
        for t in range(1, k):
            q[t] = desc[t] ^ gf_mul(a, q[t - 1])
        q_asc = q[::-1]                     # 升幂：q_asc[i] = x^i 的系数

        # 3) 分母 d_j = Q_j(a)
        d = 0
        for i in range(k - 1, -1, -1):      # Horner 求值
            d = gf_mul(d, a) ^ q_asc[i]
        if d == 0:                          # 理论上不会发生（x_j 互异）
            return None

        # 4) 累加 (y_j / d_j) · Q_j(x)
        scale = gf_mul(ys[j], gf_inv(d))
        for i in range(k):
            D[i] ^= gf_mul(scale, q_asc[i])

    return bytes(D)
