"""
文本隐水印 CLI 命令行工具

用法:
  # 嵌入水印（输出到文件）
  python cli.py embed -i input.txt -o output.txt -w "张三|2026-09-06" -p mypassword

  # 嵌入水印（输出到终端）
  python cli.py embed -i input.txt -w "张三|2026-09-06" -p mypassword

  # 提取水印
  python cli.py extract -i output.txt -p mypassword

  # 检测文本是否包含水印
  python cli.py check -i output.txt

  # 清除水印
  python cli.py remove -i output.txt -o clean.txt
"""

import argparse
import sys
from text_watermark import TextWatermark


def cmd_embed(args):
    """嵌入水印"""
    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    twm = TextWatermark(password=args.password)
    text_wm = twm.add_wm_rnd(text, args.watermark)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text_wm)
        zwm_count = TextWatermark.count_zwm(text_wm)
        print(f"水印已嵌入 → {args.output}")
        print(f"  水印内容: {args.watermark}")
        print(f"  隐藏字符数: {zwm_count}")
        print(f"  原文长度: {len(text)} 字符 → 加水印后: {len(text_wm)} 字符")
    else:
        sys.stdout.write(text_wm)
        sys.stdout.write("\n")


def cmd_extract(args):
    """提取水印"""
    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    twm = TextWatermark(password=args.password)
    result = twm.extract(text)

    if result is not None:
        print(f"提取成功！水印内容: {result}")
    else:
        print("未检测到有效水印，或密码错误。")


def cmd_check(args):
    """检测水印"""
    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    has_wm = TextWatermark.has_watermark(text)
    zwm_count = TextWatermark.count_zwm(text)

    if has_wm:
        print(f"检测到隐藏水印！零宽字符数量: {zwm_count}")
        print(f"  预估水印数据量: {zwm_count // 8} 字节")
    else:
        print("未检测到隐藏水印字符。")


def cmd_remove(args):
    """清除水印"""
    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    twm = TextWatermark(password=args.password)
    clean_text = twm.remove_watermark(text)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(clean_text)
        print(f"水印已清除 → {args.output}")
    else:
        sys.stdout.write(clean_text)
        sys.stdout.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="文本隐水印工具 - 在文本中嵌入/提取不可见的水印信息",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python cli.py embed -i doc.txt -o doc_wm.txt -w "作者:张三" -p mySecret
  python cli.py extract -i doc_wm.txt -p mySecret
  python cli.py check -i doc_wm.txt
  python cli.py remove -i doc_wm.txt -o doc_clean.txt
""")
    sub = parser.add_subparsers(dest="command", help="子命令")

    # embed
    p_embed = sub.add_parser("embed", help="嵌入水印")
    p_embed.add_argument("-i", "--input", required=True, help="输入文本文件路径")
    p_embed.add_argument("-o", "--output", help="输出文件路径（省略则输出到终端）")
    p_embed.add_argument("-w", "--watermark", required=True, help="水印内容")
    p_embed.add_argument("-p", "--password", required=True, help="加密密码")
    p_embed.set_defaults(func=cmd_embed)

    # extract
    p_extract = sub.add_parser("extract", help="提取水印")
    p_extract.add_argument("-i", "--input", required=True, help="输入文本文件路径")
    p_extract.add_argument("-p", "--password", required=True, help="加密密码")
    p_extract.set_defaults(func=cmd_extract)

    # check
    p_check = sub.add_parser("check", help="检测是否含有水印")
    p_check.add_argument("-i", "--input", required=True, help="输入文本文件路径")
    p_check.set_defaults(func=cmd_check)

    # remove
    p_remove = sub.add_parser("remove", help="清除水印")
    p_remove.add_argument("-i", "--input", required=True, help="输入文本文件路径")
    p_remove.add_argument("-o", "--output", help="输出文件路径（省略则输出到终端）")
    p_remove.set_defaults(func=cmd_remove)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
