# 隐水印工具（文本 / 图片）

一套用于**版权溯源与防泄露**的隐水印工具，支持两类载体：

- **文本隐水印**：在纯文本中用不可见零宽字符嵌入加密水印（跨平台、肉眼不可见）。
- **图片盲水印**：基于 DCT 频域盲水印，抗裁剪、抗等比放大、抗 JPEG 重压缩（载体被破坏后仍可提取）。

此外还提供 **Word / PDF 文件水印** 的适配器，统一走同一套密码体系。

参考项目：[text_blind_watermark](https://github.com/guofei9987/text_blind_watermark)（文本零宽方案启发）

---

## 目录

- [一、文本隐水印](#一文本隐水印)
- [二、图片盲水印](#二图片盲水印)
- [三、文件水印（Word / PDF / 图片）](#三文件水印word--pdf--图片)
- [四、GUI 图形界面](#四gui-图形界面)
- [五、依赖与安装](#五依赖与安装)
- [六、测试](#六测试)
- [文件结构](#文件结构)

---

## 一、文本隐水印

### 原理

利用**零宽 Unicode 字符**（Zero-Width Characters）将加密后的水印编码为二进制，嵌入文本中：

```
水印文本 → 密码加密 → 二进制 0/1 → 零宽字符替换 → 插入正文
```

- `U+2060` (WORD JOINER) → 表示 bit 0
- `U+FEFF` (ZERO WIDTH NO-BREAK SPACE) → 表示 bit 1

这两个字符在绝大多数平台（微信、钉钉、Chrome、系统记事本等）下**完全不可见**，且支持跨平台复制粘贴。

### 安全设计

- **PBKDF2-HMAC-SHA256** 密钥派生（10 万次迭代），防止暴力破解
- **XOR 流加密**：用密码派生的 PRNG 生成密钥流，对水印进行加密
- **CRC32 校验**：提取时验证数据完整性
- **Magic Header**：识别有效水印，避免误报
- **密码错误**无法提取出水印（返回 None）

### Python API

```python
from text_watermark import TextWatermark

twm = TextWatermark(password="my_secret")

# 嵌入水印
text_with_wm = twm.add_wm_rnd("这是原始文本", "作者:张三 | 2026-09-06")

# 提取水印
watermark = twm.extract(text_with_wm)
print(watermark)  # → "作者:张三 | 2026-09-06"

# 检测是否含水印
print(TextWatermark.has_watermark(text_with_wm))  # → True

# 清除水印
clean = twm.remove_watermark(text_with_wm)
```

### CLI 命令行

```bash
# 嵌入水印
python cli.py embed -i input.txt -o output.txt -w "作者:张三" -p mypassword

# 提取水印
python cli.py extract -i output.txt -p mypassword

# 检测是否含水印
python cli.py check -i output.txt

# 清除水印
python cli.py remove -i output.txt -o clean.txt
```

### 运行示例

```bash
python demo.py
```

### 文本 API 说明

| 方法 | 说明 |
|---|---|
| `add_wm_rnd(text, wm)` | 在随机位置嵌入水印 |
| `add_wm_at_first(text, wm)` | 在文本开头嵌入水印 |
| `add_wm_at_last(text, wm)` | 在文本末尾嵌入水印 |
| `add_wm_at_idx(text, wm, idx)` | 在指定位置嵌入水印 |
| `extract(text)` | 提取水印（需相同密码） |
| `remove_watermark(text)` | 清除文本中的水印 |
| `has_watermark(text)` | 检测是否含水印（静态方法） |
| `count_zwm(text)` | 统计零宽字符数（静态方法） |

### 文本兼容性

经测试，水印在以下场景下保持隐藏：

- Chrome 浏览器（包括知乎、微博等网页版）
- Windows / macOS 系统记事本
- 微信、钉钉（跨平台）
- GitHub 上的文本/代码文件
- 支持 Ctrl+C/V 复制粘贴跨平台传输

### 文本水印格式

```
[Magic Header 4B] [水印长度 4B] [加密数据 nB] [CRC32 4B]
```

每个字节编码为 8 个零宽字符，总隐藏字符数 = `(n + 12) × 8`。

### 文本限制

- 仅支持纯文本（.txt），不支持 .md / .docx 等
- 文本被大幅修改后可能无法提取
- 部分平台可能在特定操作下丢失零宽字符（如 Markdown 渲染）

---

## 二、图片盲水印

基于 **DCT（离散余弦变换）频域** 的盲水印：把水印比特写入 8×8 块低频系数对，提取端不依赖原图，**破坏式攻击后仍可提取**。

### 抗攻击能力

| 攻击类型 | 支持情况 |
|---|---|
| JPEG 重压缩（q50~q95） | ✅ 可提取 |
| 任意位置裁剪（中心/四角/只留 1/4） | ✅ 可提取 |
| 等比放大（1.25x~2.5x） | ✅ 可提取 |
| 裁剪 + JPEG / 放大 + JPEG 组合攻击 | ✅ 可提取 |
| 缩小（<1.0）/ 旋转 | ⚠️ 已知边界（v2.1 待增强） |

> 视觉不可见性：嵌入后 PSNR ≈ 32 dB（轻微可见）。当前 `_DELTA2` 控制鲁棒边际而非隐形度，降低它并不会更隐形。更高隐形需改用感知掩码或更高频系数对（v2.1 规划）。

### Python API

```python
from text_watermark_files import embed_file, extract_file

# 嵌入：输入图片 + 水印文本 + 密码 → 返回含水印图片路径
out = embed_file("input.png", "版权所有:李佳朗 | 2026", "my_secret")

# 提取：需相同密码
wm = extract_file(out, "my_secret")
print(wm)  # → "版权所有:李佳朗 | 2026"
```

- `embed_file(input_path, wm, password, output_path=None)` → 自动按扩展名路由到图片嵌入
- `extract_file(input_path, password)` → 图片走 v2 盲水印提取；失败自动降级到 v1

---

## 三、文件水印（Word / PDF / 图片）

`text_watermark_files.py` 提供**统一入口**，按文件扩展名自动路由到对应适配器：

| 扩展名 | 适配器 | 说明 |
|---|---|---|
| `.txt` | 文本零宽水印 | 见第一节 |
| `.docx` | python-docx 适配器 | 在文档元数据/结构中嵌入 |
| `.pdf` | PyMuPDF 适配器 | 在 PDF 中嵌入 |
| `.png` / `.jpg` / `.jpeg` | 图片盲水印 v2 | 见第二节 |

```python
from text_watermark_files import embed_file, extract_file

# 嵌入（自动识别类型）
out = embed_file("合同.docx", "机密:仅限内部", "pwd", output_path="合同_带水印.docx")
out = embed_file("报告.pdf",  "机密:仅限内部", "pwd", output_path="报告_带水印.pdf")

# 提取
print(extract_file("合同_带水印.docx", "pwd"))
print(extract_file("报告_带水印.pdf",  "pwd"))
```

---

## 四、GUI 图形界面

`app.py` 提供一个 Tkinter 图形界面，支持**文本 / Word / PDF / 图片**四类载体的嵌入、提取、检测、清除。

```bash
python app.py
```

界面含以下标签页：

- **嵌入**：输入文本或选择文件 + 密码 → 生成带水印内容/文件
- **提取**：粘贴文本或选择文件 + 密码 → 还原水印
- **文件**：直接对 Word / PDF / 图片文件做嵌入与提取
- **关于**：能力说明（含图片水印「抗裁剪、抗等比放大」说明）

> 注意：GUI 需要 `tkinter`（Python 标准库自带）。Windows 一般默认包含；Linux 需 `sudo apt install python3-tk`。

---

## 五、依赖与安装

```bash
pip install -r requirements.txt
```

依赖清单（已在 Python 3.12 验证）：

| 包 | 用途 |
|---|---|
| `numpy` | 矩阵运算 / DCT |
| `Pillow` | 图像处理 |
| `opencv-python` | 图像缩放与色彩空间转换 |
| `python-docx` | Word 文件水印适配器 |
| `PyMuPDF` | PDF 文件水印适配器 |
| `tkinter` | GUI（标准库自带，无需 pip） |

> 打包成独立 exe 见 `verify_exe.py` 与 `TextWatermark.spec`（使用 PyInstaller，需 `--collect-all cv2`）。

---

## 六、测试

仓库内含三套鲁棒性 / 性能测试脚本，可重复运行：

| 脚本 | 验证内容 |
|---|---|
| `test_effect.py` | 图片水印全攻击矩阵（JPEG/裁剪/放大/组合），输出 `test_effect_report.md` |
| `test_delta_sweep.py` | `_DELTA2` 隐形性 vs 鲁棒性扫描，输出 `test_delta_sweep_report.md` |
| `test_speed_optimization.py` | 放大提取速度优化前后对比，输出 `test_speed_optimization_report.md` |

```bash
python test_effect.py
python test_delta_sweep.py
python test_speed_optimization.py
```

`verify_exe.py` 用于打包后校验版本元数据和 GUI 启动冒烟。

---

## 文件结构

```
text_watermark.py          # 文本零宽水印引擎（TextWatermark 类）
text_watermark_files.py    # 图片盲水印 + Word/PDF/图片 统一适配入口
rs_codec.py                # Reed-Solomon 纠错（text_watermark.py 依赖）
app.py                     # Tkinter 图形界面（文本/Word/PDF/图片）
cli.py                     # 命令行工具（文本）
demo.py                    # 文本水印使用示例
verify_exe.py              # PyInstaller 打包后版本/启动校验
test_effect.py             # 图片水印鲁棒性测试
test_delta_sweep.py        # _DELTA2 隐形/鲁棒扫描
test_speed_optimization.py # 放大提取速度对比
requirements.txt           # 依赖清单
README.md                  # 本文件
```

样例图（供测试/演示）：`d6_src.png` `d6_src_wm.png` `d7_src.png` `d7_src_wm.png` `d8_src.png` `d8_wm.png`
