# 文本隐水印工具

在纯文本中嵌入**肉眼不可见**的水印信息，用于文档溯源和版权保护。

参考项目：[text_blind_watermark](https://github.com/guofei9987/text_blind_watermark)

## 原理

利用**零宽 Unicode 字符**（Zero-Width Characters）将加密后的水印编码为二进制，嵌入文本中：

```
水印文本 → 密码加密 → 二进制 0/1 → 零宽字符替换 → 插入正文
```

- `U+2060` (WORD JOINER) → 表示 bit 0
- `U+FEFF` (ZERO WIDTH NO-BREAK SPACE) → 表示 bit 1

这两个字符在绝大多数平台（微信、钉钉、Chrome、系统记事本等）下**完全不可见**，且支持跨平台复制粘贴。

## 安全设计

- **PBKDF2-HMAC-SHA256** 密钥派生（10 万次迭代），防止暴力破解
- **XOR 流加密**：用密码派生的 PRNG 生成密钥流，对水印进行加密
- **CRC32 校验**：提取时验证数据完整性
- **Magic Header**：识别有效水印，避免误报
- **密码错误**无法提取出水印（返回 None）

## 文件结构

```
text_watermark.py   # 核心水印引擎（TextWatermark 类）
cli.py              # 命令行工具
demo.py             # 使用示例
README.md           # 本文件
```

## 快速开始

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

## API 说明

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

## 兼容性

经测试，水印在以下场景下保持隐藏：

- Chrome 浏览器（包括知乎、微博等网页版）
- Windows / macOS 系统记事本
- 微信、钉钉（跨平台）
- GitHub 上的文本/代码文件
- 支持 Ctrl+C/V 复制粘贴跨平台传输

## 水印格式

```
[Magic Header 4B] [水印长度 4B] [加密数据 nB] [CRC32 4B]
```

每个字节编码为 8 个零宽字符，总隐藏字符数 = `(n + 12) × 8`。

## 限制

- 仅支持纯文本（.txt），不支持 .md / .docx 等
- 文本被大幅修改后可能无法提取
- 部分平台可能在特定操作下丢失零宽字符（如 Markdown 渲染）
