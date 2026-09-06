"""
文本隐水印引擎 v3 —— 双方案冗余

两套互补的嵌入方案同时存在于文本中（用不同零宽字符集区分）：

  方案 A · 位置编码 + Reed-Solomon 纠删  → 抗「零宽字符被随机剥离」
  方案 B · 多份完整副本 + 8 偏移重同步   → 抗「文本被截断 / 编辑」

────────────────────────────────────────────────────────────
方案 A 的关键洞察
────────────────────────────────────────────────────────────
纯文本未被改动、仅零宽字符被剥离时，**可见文本不变 → 字符间隙编号
依然有效**。于是每个间隙都是一个「坐标」，缺失的位不是漂移，而是
**位置已知的擦除（erasure）**。这把难题从"同步问题"变成了标准的
"纠删问题"，而纠删正是 RS 的拿手好戏（MDS 性质：幸存符号 ≥ k 即可
100% 恢复）。

  编码：明文 → 加密 → 封包 → RS 编码(k→n) → bit 流
  分布：每个 bit 存 R 份副本于不同间隙（P(bit 丢失) = p^R）
  解码：按间隙坐标重建 bit 流 → 缺失位标记为擦除 → RS 恢复

这样即便全篇随机丢失 30%~40% 的零宽字符，仍能完整还原水印。
（相比之下，v2.2 的重复码在均匀随机剥离下几乎无能为力。）

────────────────────────────────────────────────────────────
方案 B（v2.2 已验证）
────────────────────────────────────────────────────────────
多份「完整且字节对齐」的封包副本分散全文；删除会让副本起点漂移 d
位，而字节对齐只取决于 d%8，故解码只需试 8 个比特偏移。
擅长应对文本被截断/编辑（此时间隙坐标失效，方案 A 不可用）。

零宽字符分配：
  方案 A：U+200B(bit0) / U+200C(bit1)
  方案 B：U+200D(bit0) / U+2061(bit1)
  备用  ：U+2062(bit0) / U+2063(bit1)
  旧版v1：U+2060(bit0) / U+FEFF(bit1) —— 仅用于提取历史水印
"""

import hashlib
import hmac
import struct
import zlib
import random as _random
from typing import Dict, List, Optional, Tuple

from rs_codec import rs_encode, rs_decode

# ── 零宽字符定义 ──────────────────────────────────────────────
CHARSET_A: Tuple[str, str] = (chr(0x200B), chr(0x200C))   # 方案 A
CHARSET_B: Tuple[str, str] = (chr(0x200D), chr(0x2061))   # 方案 B
CHARSET_C: Tuple[str, str] = (chr(0x2062), chr(0x2063))   # 备用
CHR_V1_ZERO = chr(0x2060)   # 旧版 v1 bit0
CHR_V1_ONE = chr(0xFEFF)    # 旧版 v1 bit1（BOM，仅用于识别旧水印）

ZWM_CHARS = {*CHARSET_A, *CHARSET_B, *CHARSET_C, CHR_V1_ZERO, CHR_V1_ONE}

MAGIC_V2 = b"TWM2"
MAGIC_V1 = b"TWM1"

# 封包固定开销：MAGIC(4) + 长度(2) + CRC16(2)
HDR = 8
# 标准数据符号数（RS 的 k）。量化为若干标准值，使解码端无需知道
# 水印长度就能重算出与编码端相同的参数（只需枚举这几个值）。
# 档位越细，容量浪费越少、抗剥离能力越强，代价是解码时多试几次。
K_STD: List[int] = [24, 32, 40, 48, 56, 64, 80, 96, 128, 160, 192]
K_MAX = max(K_STD)          # 单个水印最大字节数 = K_MAX - HDR


class TextWatermark:
    """文本隐水印 v3：方案A（RS 纠删，抗随机剥离）+ 方案B（副本重同步，抗截断）"""

    def __init__(self, password: str | bytes):
        if isinstance(password, str):
            password = password.encode("utf-8")
        self.password = password
        self._key_cache: Optional[bytes] = None

    # ── 密钥与加密（HMAC-SHA256-CTR 流密码）────────────────────
    def _derive_key(self, salt: bytes = b"text_wm_v2") -> bytes:
        if self._key_cache is None:
            self._key_cache = hashlib.pbkdf2_hmac(
                "sha256", self.password, salt, 100_000, dklen=32
            )
        return self._key_cache

    def _keystream(self, length: int) -> bytes:
        key = self._derive_key()
        out = bytearray()
        ctr = 0
        while len(out) < length:
            blk = hmac.new(key, struct.pack(">Q", ctr), hashlib.sha256).digest()
            out += blk
            ctr += 1
        return bytes(out[:length])

    def _encrypt(self, data: bytes) -> bytes:
        return bytes(a ^ b for a, b in zip(data, self._keystream(len(data))))

    def _decrypt(self, data: bytes) -> bytes:
        return self._encrypt(data)

    # ── 旧版 v1（兼容历史水印）─────────────────────────────────
    @staticmethod
    def _v1_derive_key(password: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password, b"text_wm_v1", 100_000, dklen=32)

    def _v1_decrypt(self, data: bytes) -> bytes:
        key = self._v1_derive_key(self.password)
        rng = _random.Random(int.from_bytes(key, "big"))
        mask = bytes(rng.randint(0, 255) for _ in range(len(data)))
        return bytes(a ^ b for a, b in zip(data, mask))

    # ── bit / 字节 转换 ────────────────────────────────────────
    @staticmethod
    def _bytes_to_bits(data: bytes) -> List[int]:
        return [(byte >> (7 - i)) & 1 for byte in data for i in range(8)]

    @staticmethod
    def _bits_to_bytes(bits: List[int]) -> bytes:
        res = bytearray()
        for i in range(0, len(bits) - len(bits) % 8, 8):
            chunk = bits[i:i + 8]
            res.append(sum(b << (7 - j) for j, b in enumerate(chunk)))
        return bytes(res)

    @staticmethod
    def _encode_bit(bit: int, charset: Tuple[str, str]) -> str:
        return charset[1] if bit else charset[0]

    # ── 封包 ───────────────────────────────────────────────────
    def _build_payload(self, wm: bytes) -> bytes:
        enc = self._encrypt(wm)
        if len(enc) + HDR > K_MAX:
            raise ValueError(f"水印过长：最多 {K_MAX - HDR} 字节（UTF-8）")
        body = MAGIC_V2 + struct.pack(">H", len(enc)) + enc
        crc = zlib.crc32(body) & 0xFFFF
        return body + struct.pack(">H", crc)

    # ── 方案 A：参数规划与间隙排列 ─────────────────────────────
    @staticmethod
    def _plan_a(gaps: int, k: int) -> Optional[Tuple[int, int]]:
        """在容量与 RS 约束下，挑选抗均匀剥离能力最强的 (R, n)。

        字节擦除率 e = 1-(1-p^R)^8 必须 ≤ 可容忍擦除率 ρ = 1-k/n。
        枚举 R 与 n，最大化可容忍的 p。
        """
        best: Optional[Tuple[float, int, int]] = None
        for R in range(1, 7):
            max_n = min(255, gaps // (8 * R))
            if max_n < k:
                continue
            for n in range(k, max_n + 1):
                rho = 1.0 - k / n                       # 可容忍字节擦除率
                base = 1.0 - (1.0 - rho) ** (1.0 / 8.0)  # 允许的单 bit 丢失率
                if base <= 0:
                    continue
                p = base ** (1.0 / R)                   # 可容忍的均匀剥离率
                if best is None or p > best[0]:
                    best = (p, R, n)
        return None if best is None else (best[1], best[2])

    def _gap_perm(self, gaps: int, m: int) -> Optional[List[int]]:
        """确定性生成 m 个互不重复的间隙索引（由密码派生，编解码端一致）。"""
        if m > gaps or m <= 0:
            return None
        h = hashlib.sha256(self.password + b"|gapperm|" + str(gaps).encode()).digest()
        rng = _random.Random(int.from_bytes(h[:8], "big"))
        return rng.sample(range(gaps), m)

    # ── 方案 A：生成插入表 ─────────────────────────────────────
    def _inserts_a(self, gaps: int, payload: bytes) -> List[Tuple[int, str]]:
        k = next((s for s in K_STD if s >= len(payload)), None)
        if k is None:
            return []
        plan = self._plan_a(gaps, k)
        if plan is None:
            return []
        R, n = plan
        data = payload + bytes(k - len(payload))          # 补齐到标准 k
        codeword = rs_encode(data, n)
        bits = self._bytes_to_bits(codeword)
        perm = self._gap_perm(gaps, len(bits) * R)
        if perm is None:
            return []
        inserts: List[Tuple[int, str]] = []
        for i, b in enumerate(bits):
            ch = self._encode_bit(b, CHARSET_A)
            for c in range(R):
                inserts.append((perm[i * R + c], ch))
        return inserts

    # ── 方案 B：生成插入表（完整副本，分散 + 不环绕）────────────
    def _inserts_b(self, gaps: int, payload: bytes, idx: int) -> List[Tuple[int, str]]:
        bits = self._bytes_to_bits(payload)
        nb = len(bits)
        # 单份副本都放不下（间隙不足）→ 交给降级路径（末尾密集追加），
        # 否则同一间隙会挤入多个 bit，插入后顺序被打乱导致无法解码。
        if nb == 0 or nb > gaps:
            return []
        copies = min(5, max(1, gaps // nb))
        rb = list(bits) * copies                 # 完整副本顺序串接
        n = len(rb)
        safe_span = max(1, gaps - n)
        base = (idx % safe_span) if idx else 0   # 不环绕，避免位序旋转
        span = gaps - base
        inserts: List[Tuple[int, str]] = []
        for j, b in enumerate(rb):
            pos = base + (0 if n <= 1 else int(round(j * (span - 1) / (n - 1))))
            inserts.append((pos, self._encode_bit(b, CHARSET_B)))
        return inserts

    # ── 嵌入 ───────────────────────────────────────────────────
    def add_wm_at_idx(self, text: str, wm: str | bytes, idx: int = 0) -> str:
        if isinstance(wm, str):
            wm = wm.encode("utf-8")
        # 先清除已有水印，保证字符间隙编号干净可复现
        clean = self.remove_watermark(text)
        gaps = len(clean) + 1
        payload = self._build_payload(wm)

        ia = self._inserts_a(gaps, payload)
        ib = self._inserts_b(gaps, payload, idx % max(1, gaps))

        if not ia and not ib:
            # 容量极低：降级为单副本密集追加
            bits = self._bytes_to_bits(payload)
            return clean + "".join(self._encode_bit(b, CHARSET_B) for b in bits)

        inserts = ia + ib
        res = list(clean)
        for g, ch in sorted(inserts, key=lambda x: x[0], reverse=True):
            res.insert(g, ch)
        return "".join(res)

    def add_wm_at_last(self, text: str, wm: str | bytes) -> str:
        return self.add_wm_at_idx(text, wm, len(text))

    def add_wm_at_first(self, text: str, wm: str | bytes) -> str:
        return self.add_wm_at_idx(text, wm, 0)

    def add_wm_rnd(self, text: str, wm: str | bytes) -> str:
        if not text:
            return self.generate_watermark(wm)
        idx = _random.SystemRandom().randint(0, len(text))
        return self.add_wm_at_idx(text, wm, idx)

    def generate_watermark(self, wm: str | bytes) -> str:
        """仅生成水印零宽串（空文本 / 纯水印串场景）。"""
        if isinstance(wm, str):
            wm = wm.encode("utf-8")
        payload = self._build_payload(wm)
        bits = self._bytes_to_bits(payload)
        return "".join(self._encode_bit(b, CHARSET_B) for b in list(bits) * 3)

    @staticmethod
    def remove_watermark(text: str) -> str:
        return "".join(c for c in text if c not in ZWM_CHARS)

    # ── 提取 ───────────────────────────────────────────────────
    def extract(self, text_with_wm: str) -> Optional[str]:
        gap_a: Dict[int, int] = {}     # 间隙编号 → 方案A 的 bit 值
        b_bits: List[int] = []         # 方案B 的 bit 序列（按文本顺序）
        v1_bits: List[int] = []
        g = 0
        for ch in text_with_wm:
            if ch == CHARSET_A[0]:
                gap_a[g] = 0
            elif ch == CHARSET_A[1]:
                gap_a[g] = 1
            elif ch == CHARSET_B[0]:
                b_bits.append(0)
            elif ch == CHARSET_B[1]:
                b_bits.append(1)
            elif ch == CHR_V1_ZERO:
                v1_bits.append(0)
            elif ch == CHR_V1_ONE:
                v1_bits.append(1)
            elif ch in ZWM_CHARS:
                pass                    # 备用字符集，忽略
            else:
                g += 1                  # 可见字符 → 推进间隙编号
        gaps = g + 1

        # ① 方案 A：位置编码 + RS 纠删（抗随机剥离）
        res = self._extract_a(gap_a, gaps)
        if res is not None:
            return res

        # ② 方案 B：完整副本 + 8 偏移重同步（抗截断/编辑）
        res = self._try_decode_b(b_bits)
        if res is not None:
            return res

        # ③ 旧版 v1
        if len(v1_bits) >= 32:
            res = self._parse_v1(self._bits_to_bytes(v1_bits))
            if res is not None:
                return res
        return None

    def _extract_a(self, gap_a: Dict[int, int], gaps: int) -> Optional[str]:
        if not gap_a:
            return None
        avail = len(gap_a)
        for k in K_STD:
            # 必要条件下界剪枝：凑出 k 个完整字节至少需要 8k 个已知 bit
            if avail < k * 8:
                continue
            plan = self._plan_a(gaps, k)
            if plan is None:
                continue
            R, n = plan
            total = n * 8 * R
            perm = self._gap_perm(gaps, total)
            if perm is None:
                continue
            # 重建 bit 流：每个 bit 的 R 个副本任一幸存即可（缺失 → 擦除）
            bits: List[Optional[int]] = []
            for i in range(n * 8):
                val: Optional[int] = None
                for c in range(R):
                    v = gap_a.get(perm[i * R + c])
                    if v is not None:
                        val = v
                        break
                bits.append(val)
            # 组字节：任一 bit 缺失则该字节整体视为擦除
            syms: List[Optional[int]] = []
            for j in range(n):
                chunk = bits[j * 8:(j + 1) * 8]
                if chunk.count(None) == 0:
                    syms.append(sum(v << (7 - t) for t, v in enumerate(chunk)))
                else:
                    syms.append(None)
            data = rs_decode(syms, k)
            if data is None:
                continue
            res = self._parse_v2(data)
            if res is not None:
                return res
        return None

    def _try_decode_b(self, bits: List[int]) -> Optional[str]:
        """8 偏移重同步：删除使副本起点漂移 d 位，而字节对齐只取决于 d%8。"""
        for off in range(8):
            if len(bits) - off < 32:
                break
            res = self._parse_v2(self._bits_to_bytes(bits[off:]))
            if res is not None:
                return res
        return None

    # ── 封包解析 ───────────────────────────────────────────────
    def _parse_v2(self, payload: bytes) -> Optional[str]:
        mlen = len(MAGIC_V2)
        for i in range(0, len(payload) - mlen - 4 + 1):
            if payload[i:i + mlen] != MAGIC_V2:
                continue
            if i + mlen + 4 > len(payload):
                continue
            wm_len = struct.unpack(">H", payload[i + mlen:i + mlen + 2])[0]
            start = i + mlen + 2
            end = start + wm_len + 2
            if end > len(payload):
                continue
            enc = payload[start:start + wm_len]
            crc_stored = struct.unpack(">H", payload[start + wm_len:end])[0]
            calc = zlib.crc32(MAGIC_V2 + struct.pack(">H", wm_len) + enc) & 0xFFFF
            if calc != crc_stored:
                continue
            dec = self._decrypt(enc)
            try:
                return dec.decode("utf-8")
            except UnicodeDecodeError:
                continue
        return None

    def _parse_v1(self, payload: bytes) -> Optional[str]:
        mlen = len(MAGIC_V1)
        for i in range(0, len(payload) - mlen - 8 + 1):
            if payload[i:i + mlen] != MAGIC_V1:
                continue
            if i + mlen + 8 > len(payload):
                continue
            wm_len = struct.unpack(">I", payload[i + mlen:i + mlen + 4])[0]
            start = i + mlen + 4
            end = start + wm_len + 4
            if end > len(payload):
                continue
            enc = payload[start:start + wm_len]
            crc_stored = struct.unpack(">I", payload[start + wm_len:end])[0]
            calc = zlib.crc32(MAGIC_V1 + struct.pack(">I", wm_len) + enc) & 0xFFFFFFFF
            if calc != crc_stored:
                continue
            dec = self._v1_decrypt(enc)
            try:
                return dec.decode("utf-8")
            except UnicodeDecodeError:
                continue
        return None

    # ── 工具方法 ───────────────────────────────────────────────
    @staticmethod
    def has_watermark(text: str) -> bool:
        return any(c in ZWM_CHARS for c in text)

    @staticmethod
    def count_zwm(text: str) -> int:
        return sum(1 for c in text if c in ZWM_CHARS)
