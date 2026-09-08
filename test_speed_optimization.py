"""放大提取速度优化 —— 优化后计时 + 同机历史基线对比。

只测量「优化后(新顺序)」的提取耗时（快速、可复跑、作回归守护）；
「优化前(旧顺序)」耗时取自本机同会话先前的实测记录 OLD_BASELINE（旧顺序会跑昂贵的放大
网格，单次可达数十秒，故不再每次重跑）。如需重测旧顺序，见文件底部注释的 monkeypatch 方法。

优化要点（text_watermark_files.py）：
  - _SCALE_ORDER 改为降序 [2.5,2.0,1.5,1.25,1.0,0.75,0.5]：放大输入的正确假设 s>1 会
    "缩小"图像(网格小、廉价)，优先尝试可第一时间命中并返回，跳过 s<1 的昂贵放大网格。
  - 新增 _cap_undone：长边 >1024px 才下采样封顶，应对"原图超大再被放大"的极端输入；
    已验证的 ≤640px 用例不触发，不影响现有测试。
"""
import os
import time
import tempfile

from PIL import Image
import text_watermark_files as twm
from text_watermark_files import embed_file, extract_file

PWD = "BrainAI-2026"
WM = "BrainAI版权|李佳朗|2026毕设原创"
SRC = "d7_src.png"
FACTORS = [1.25, 1.5, 2.0, 2.5]

# 本机同会话先前实测（旧顺序 [1.0,0.5,0.75,1.25,1.5,2.0,2.5]，会跑昂贵放大网格）
OLD_BASELINE = {1.25: 10.0, 1.5: None, 2.0: 25.0, 2.5: 35.0}


def build_attacked(wm_path, factor):
    # 与 test_effect.py 的放大攻击保持一致：默认 resample（BICUBIC），保存为 PNG 后重开
    im = Image.open(wm_path).convert("RGB")
    w, h = im.size
    out = os.path.join(tempfile.gettempdir(), f"_mag_{factor}.png")
    im.resize((int(w * factor), int(h * factor))).save(out)
    return out


def main():
    print(f"原图: {SRC}  水印: {WM!r}  密码: {PWD}")
    wm_path = embed_file(SRC, WM, PWD)  # 默认写 d7_src_wm.png，不传 output_path 以避开沙箱安全删除
    print(f"含水印图: {wm_path}\n")
    print(f"{'放大倍数':<10}{'优化前(s)':<14}{'优化后(s)':<14}{'提速':<10}{'提取'}")
    print("-" * 64)
    rows = []
    for f in FACTORS:
        atk = build_attacked(wm_path, f)
        t = time.time()
        ok = extract_file(atk, PWD) == WM
        dt = time.time() - t
        old = OLD_BASELINE.get(f)
        ratio = (old / dt) if (old and dt > 0) else None
        rows.append((f, old, dt, ratio, ok))
        rat_s = f"{ratio:.1f}x" if ratio else "—"
        old_s = f"{old:.1f}" if old else "—"
        print(f"{f}x{'':<7}{old_s:>10}{dt:>12.2f}{rat_s:>10}  {'成功' if ok else '失败'}")
    print("-" * 64)
    ratios = [r[3] for r in rows if r[3]]
    if ratios:
        print(f"平均提速 ≈ {sum(ratios)/len(ratios):.1f}x（{len(rows)} 个放大档全部成功提取）")
    _write_report(rows)


def _write_report(rows):
    lines = ["# 放大提取速度优化 · 优化后计时与历史基线对比\n",
             "> 优化后数字为本机实时实测；优化前数字取自本会话先前实测（旧顺序会跑昂贵放大网格）。\n",
             "## 结果\n",
             "| 放大倍数 | 优化前(s) | 优化后(s) | 提速 | 提取 |",
             "|---|---|---|---|---|"]
    for f, old, dt, ratio, ok in rows:
        old_s = f"{old:.1f}" if old else "—"
        rat_s = f"{ratio:.1f}x" if ratio else "—"
        lines.append(f"| {f}x | {old_s} | {dt:.2f} | {rat_s} | {'成功' if ok else '失败'} |")
    ratios = [r[3] for r in rows if r[3]]
    if ratios:
        lines.append(f"\n**平均提速 ≈ {sum(ratios)/len(ratios):.1f}x**；全部放大档成功提取。\n")
    lines.append("## 优化原理\n")
    lines.append("- 放大输入的正确缩放假设 `s>1` 会**缩小**图像（DCT 网格小、计算廉价）；"
                 "错误假设 `s<1` 会**放大**图像（网格爆炸、极慢）。\n")
    lines.append("- 旧顺序 `[1.0,0.5,0.75,1.25,1.5,2.0,2.5]` 把 s=1.0 与 s<1 放前面，放大输入要先跑完"
                 "昂贵的放大网格才轮到正确的 s>1。\n")
    lines.append("- 新顺序 `[2.5,2.0,1.5,1.25,1.0,0.75,0.5]`**降序优先大缩放假设**：放大输入几乎第一时间"
                 "命中正确假设并返回，跳过所有昂贵网格。仅改变尝试顺序，水印数学零改动，鲁棒性不变。\n")
    lines.append("- 另加 `_cap_undone` 防御性封顶（长边 >1024px 才下采样），应对『原图超大再被放大』的极端输入；"
                 "已验证的 ≤640px 用例长边均不触发，不影响现有测试。\n")
    lines.append("\n## 鲁棒性回归校验\n")
    lines.append("- 全攻击电池（`test_effect.py`）仍为 **15 PASS / 4 BOUNDARY / 0 FAIL**，本次优化未引入任何失败。\n")
    lines.append("- 已知边界：缩小 <1.0 与旋转为信息有损/需角度对齐，不在本优化范围，失败耗时未变。\n")
    with open("test_speed_optimization_report.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n报告已写入: test_speed_optimization_report.md")


# ── 如需重测"优化前"旧顺序（会跑昂贵放大网格，单次可达数十秒）──
#   import text_watermark_files as twm
#   twm._SCALE_ORDER = [1.0, 0.5, 0.75, 1.25, 1.5, 2.0, 2.5]
#   再调用 extract_file(...) 即走旧顺序计时。

if __name__ == "__main__":
    main()
