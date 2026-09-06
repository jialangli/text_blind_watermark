"""
文本隐水印 - 使用示例

运行: python demo.py
"""

from text_watermark import TextWatermark


def demo_basic():
    """基本用法：嵌入与提取"""
    print("=" * 60)
    print("示例 1: 基本嵌入与提取")
    print("=" * 60)

    original_text = "这是一段重要的文档内容。版权所有，未经授权请勿转载。"
    watermark = "作者:张三 | 日期:2026-09-06 | ID:WM-001"
    password = "my_secret_key"

    twm = TextWatermark(password=password)

    # 嵌入水印
    text_with_wm = twm.add_wm_rnd(original_text, watermark)
    print(f"原文: {original_text}")
    print(f"加水印后（看起来一样）: {text_with_wm}")
    print(f"水印内容: {watermark}")
    print(f"零宽字符数: {TextWatermark.count_zwm(text_with_wm)}")
    print(f"肉眼可见文本一致: {original_text == TextWatermark.remove_watermark(text_with_wm)}")

    # 提取水印
    extracted = twm.extract(text_with_wm)
    print(f"提取水印: {extracted}")
    print(f"提取成功: {extracted == watermark}")


def demo_wrong_password():
    """错误密码验证"""
    print("\n" + "=" * 60)
    print("示例 2: 错误密码无法提取")
    print("=" * 60)

    text = "这是一段机密文档。"
    twm = TextWatermark(password="correct_pwd")
    text_wm = twm.add_wm_rnd(text, "机密水印内容")

    # 正确密码
    correct = twm.extract(text_wm)
    print(f"正确密码提取: {correct}")

    # 错误密码
    twm_wrong = TextWatermark(password="wrong_pwd")
    wrong = twm_wrong.extract(text_wm)
    print(f"错误密码提取: {wrong}")


def demo_multiple_positions():
    """不同位置嵌入"""
    print("\n" + "=" * 60)
    print("示例 3: 不同嵌入位置")
    print("=" * 60)

    text = "春眠不觉晓，处处闻啼鸟。夜来风雨声，花落知多少。"
    twm = TextWatermark(password="poem_pwd")

    # 开头插入
    wm_first = twm.add_wm_at_first(text, "开头水印")
    # 末尾插入
    wm_last = twm.add_wm_at_last(text, "末尾水印")
    # 随机插入
    wm_rnd = twm.add_wm_rnd(text, "随机水印")

    print(f"开头水印 → 提取: {twm.extract(wm_first)}")
    print(f"末尾水印 → 提取: {twm.extract(wm_last)}")
    print(f"随机水印 → 提取: {twm.extract(wm_rnd)}")


def demo_long_text():
    """长文本测试"""
    print("\n" + "=" * 60)
    print("示例 4: 长文本水印")
    print("=" * 60)

    long_text = "这是一篇关于信息安全的技术文档。" * 50
    watermark_info = "作者:李四 | 部门:研发部 | 文档编号:DOC-2026-0001 | 密级:内部公开"

    twm = TextWatermark(password="doc_pwd_2026")
    text_wm = twm.add_wm_rnd(long_text, watermark_info)

    extracted = twm.extract(text_wm)
    print(f"原文长度: {len(long_text)} 字符")
    print(f"水印长度: {len(watermark_info)} 字符")
    print(f"零宽字符数: {TextWatermark.count_zwm(text_wm)}")
    print(f"提取水印: {extracted}")
    print(f"提取成功: {extracted == watermark_info}")


def demo_removal():
    """水印清除"""
    print("\n" + "=" * 60)
    print("示例 5: 水印清除")
    print("=" * 60)

    text = "需要保护的内容，但有时候也需要清除水印。"
    twm = TextWatermark(password="remove_pwd")
    text_wm = twm.add_wm_rnd(text, "临时水印")

    print(f"含水印检测: {TextWatermark.has_watermark(text_wm)}")

    clean_text = twm.remove_watermark(text_wm)
    print(f"清除后检测: {TextWatermark.has_watermark(clean_text)}")
    print(f"文本内容恢复: {clean_text == text}")


if __name__ == "__main__":
    demo_basic()
    demo_wrong_password()
    demo_multiple_positions()
    demo_long_text()
    demo_removal()
    print("\n所有示例运行完成！")
