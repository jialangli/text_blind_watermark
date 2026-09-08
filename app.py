"""
隐水印工具 - 桌面 GUI 应用（文本 / Word / PDF / 图片）

运行: python app.py
打包: pyinstaller --onefile --windowed --name 隐水印工具 app.py
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import sys

from text_watermark import TextWatermark
from text_watermark_files import embed_file, extract_file


class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title("隐水印工具 · 文本 / Word / PDF / 图片")
        self.root.geometry("820x640")
        self.root.minsize(720, 580)

        self._setup_style()
        self._build_ui()
        self._update_stats()

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = "#f5f5f5"
        accent = "#2563eb"

        style.configure(".", background=bg, foreground="#1a1a1a", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("TLabel", background=bg, font=("Microsoft YaHei UI", 10))
        style.configure("Card.TLabel", background="#ffffff")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"), background=bg, foreground="#1a1a1a")
        style.configure("Hint.TLabel", font=("Microsoft YaHei UI", 9), background=bg, foreground="#888888")
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"), foreground="#ffffff")
        style.map("Accent.TButton",
                  background=[("active", accent), ("!active", accent)],
                  foreground=[("active", "#ffffff"), ("!active", "#ffffff")])
        style.configure("TNotebook", background=bg, tabmargins=[8, 4, 8, 0])
        style.configure("TNotebook.Tab", padding=[16, 6], font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", "#ffffff"), ("!selected", "#e0e0e0")],
                  foreground=[("selected", accent), ("!selected", "#555555")])

        self.root.configure(bg=bg)

    def _build_ui(self):
        # 顶部标题栏
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=20, pady=(16, 8))
        ttk.Label(header, text="文本隐水印工具", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  在文本中嵌入肉眼不可见的水印", style="Hint.TLabel").pack(side="left", padx=(4, 0), pady=(6, 0))

        # 选项卡
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        self.tab_embed = ttk.Frame(notebook)
        self.tab_extract = ttk.Frame(notebook)
        self.tab_file = ttk.Frame(notebook)
        notebook.add(self.tab_embed, text="  文本嵌入  ")
        notebook.add(self.tab_extract, text="  文本提取  ")
        notebook.add(self.tab_file, text="  文件水印  ")
        notebook.add(self._build_about_tab(notebook), text="  关于  ")

        self._build_embed_tab()
        self._build_extract_tab()
        self._build_file_tab()

    def _build_embed_tab(self):
        tab = self.tab_embed
        pad = {"padx": 16, "pady": (4, 4)}

        # 水印内容
        frm_wm = ttk.Frame(tab)
        frm_wm.pack(fill="x", **pad)
        ttk.Label(frm_wm, text="水印内容：").pack(side="left")
        self.wm_var = tk.StringVar()
        ttk.Entry(frm_wm, textvariable=self.wm_var, width=50).pack(side="left", padx=(4, 0), fill="x", expand=True)

        # 密码 + 位置
        frm_opt = ttk.Frame(tab)
        frm_opt.pack(fill="x", **pad)
        ttk.Label(frm_opt, text="密码：").pack(side="left")
        self.pwd_embed = tk.StringVar()
        ttk.Entry(frm_opt, textvariable=self.pwd_embed, show="*", width=18).pack(side="left", padx=(4, 0))
        ttk.Label(frm_opt, text="    嵌入位置：").pack(side="left")
        self.pos_var = tk.StringVar(value="随机")
        for text, val in [("随机", "rnd"), ("开头", "first"), ("末尾", "last")]:
            ttk.Radiobutton(frm_opt, text=text, variable=self.pos_var, value=val).pack(side="left", padx=(2, 0))

        # 文本框
        frm_text = ttk.Frame(tab)
        frm_text.pack(fill="both", expand=True, **pad)
        ttk.Label(frm_text, text="文本内容：").pack(anchor="w")
        self.embed_text = scrolledtext.ScrolledText(frm_text, height=12, wrap="word",
                                                    font=("Microsoft YaHei UI", 10),
                                                    undo=True)
        self.embed_text.pack(fill="both", expand=True, pady=(4, 0))

        # 按钮栏
        frm_btn = ttk.Frame(tab)
        frm_btn.pack(fill="x", **pad)
        ttk.Button(frm_btn, text="嵌入水印", style="Accent.TButton", command=self.do_embed).pack(side="left")
        ttk.Button(frm_btn, text="从文件导入", command=self.embed_import).pack(side="left", padx=(8, 0))
        ttk.Button(frm_btn, text="保存到文件", command=self.embed_export).pack(side="left", padx=(8, 0))
        ttk.Button(frm_btn, text="清空", command=self.embed_clear).pack(side="left", padx=(8, 0))

        # 状态
        self.embed_status = tk.StringVar(value="就绪")
        ttk.Label(tab, textvariable=self.embed_status, style="Hint.TLabel").pack(anchor="w", padx=16, pady=(4, 0))

    def _build_extract_tab(self):
        tab = self.tab_extract
        pad = {"padx": 16, "pady": (4, 4)}

        # 密码
        frm_pwd = ttk.Frame(tab)
        frm_pwd.pack(fill="x", **pad)
        ttk.Label(frm_pwd, text="密码：").pack(side="left")
        self.pwd_extract = tk.StringVar()
        ttk.Entry(frm_pwd, textvariable=self.pwd_extract, show="*", width=20).pack(side="left", padx=(4, 0))
        ttk.Button(frm_pwd, text="提取水印", style="Accent.TButton", command=self.do_extract).pack(side="right")

        # 文本框
        frm_text = ttk.Frame(tab)
        frm_text.pack(fill="both", expand=True, **pad)
        ttk.Label(frm_text, text="含水印文本：").pack(anchor="w")
        self.extract_text = scrolledtext.ScrolledText(frm_text, height=10, wrap="word",
                                                      font=("Microsoft YaHei UI", 10))
        self.extract_text.pack(fill="both", expand=True, pady=(4, 0))

        # 结果
        frm_result = ttk.Frame(tab)
        frm_result.pack(fill="x", **pad)
        ttk.Label(frm_result, text="提取结果：").pack(anchor="w")
        self.result_label = tk.Label(frm_result, text="（等待提取）", font=("Microsoft YaHei UI", 11, "bold"),
                                     fg="#2563eb", bg="#f5f5f5")
        self.result_label.pack(anchor="w", pady=(2, 4))
        self.result_stats = tk.StringVar(value="")
        ttk.Label(frm_result, textvariable=self.result_stats, style="Hint.TLabel").pack(anchor="w")

        # 工具按钮
        frm_btn = ttk.Frame(tab)
        frm_btn.pack(fill="x", **pad)
        ttk.Button(frm_btn, text="从文件导入", command=self.extract_import).pack(side="left")
        ttk.Button(frm_btn, text="检测水印", command=self.do_check).pack(side="left", padx=(8, 0))
        ttk.Button(frm_btn, text="清除水印", command=self.do_remove).pack(side="left", padx=(8, 0))
        ttk.Button(frm_btn, text="清空", command=self.extract_clear).pack(side="left", padx=(8, 0))

    # ── 文件水印页（Word / PDF / 图片）───────────────────
    def _build_file_tab(self):
        tab = self.tab_file
        pad = {"padx": 16, "pady": (4, 4)}

        ttk.Label(tab, text="支持 Word(.docx) / PDF(.pdf) / 图片(.png .jpg)，嵌入后生成 _wm 副本，原文件不变",
                  style="Hint.TLabel").pack(anchor="w", padx=16, pady=(8, 2))

        # 文件选择
        frm_file = ttk.Frame(tab)
        frm_file.pack(fill="x", **pad)
        ttk.Label(frm_file, text="文件：").pack(side="left")
        self.file_path = tk.StringVar()
        ttk.Entry(frm_file, textvariable=self.file_path, width=58).pack(side="left", padx=(4, 0),
                                                                        fill="x", expand=True)
        ttk.Button(frm_file, text="选择…", command=self.file_pick).pack(side="left", padx=(8, 0))

        # 水印内容 + 密码
        frm_opt = ttk.Frame(tab)
        frm_opt.pack(fill="x", **pad)
        ttk.Label(frm_opt, text="水印内容：").pack(side="left")
        self.file_wm = tk.StringVar()
        ttk.Entry(frm_opt, textvariable=self.file_wm, width=26).pack(side="left", padx=(4, 0))
        ttk.Label(frm_opt, text="  密码：").pack(side="left")
        self.file_pwd = tk.StringVar()
        ttk.Entry(frm_opt, textvariable=self.file_pwd, show="*", width=16).pack(side="left", padx=(4, 0))

        # 操作按钮
        frm_btn = ttk.Frame(tab)
        frm_btn.pack(fill="x", **pad)
        ttk.Button(frm_btn, text="嵌入水印", style="Accent.TButton",
                   command=self.file_embed).pack(side="left")
        ttk.Button(frm_btn, text="提取水印", style="Accent.TButton",
                   command=self.file_extract).pack(side="left", padx=(8, 0))

        # 结果
        frm_res = ttk.Frame(tab)
        frm_res.pack(fill="both", expand=True, **pad)
        ttk.Label(frm_res, text="操作结果：").pack(anchor="w")
        self.file_result = tk.Text(frm_res, height=8, wrap="word",
                                   font=("Microsoft YaHei UI", 10),
                                   bg="#ffffff", fg="#333333", relief="solid",
                                   borderwidth=1)
        self.file_result.pack(fill="both", expand=True, pady=(4, 0))
        self.file_result.insert("1.0", "选择文件后可嵌入或提取。\n"
                                       "· 嵌入：生成「原名_wm」新文件，原文件不被修改；\n"
                                       "· 提取：输入正确密码读回水印；图片建议用原图（无压缩）提取最准。")
        self.file_result.config(state="disabled")

        # 能力说明
        ttk.Label(tab,
                  text="图片为全网格频域盲水印：抗裁剪（网格相位搜索恢复）、抗等比放大、"
                       "抗微信/网页重压缩（实测 JPEG q85 可提取）；"
                       "Word/PDF 用隐藏字符/透明层，可再编辑保存",
                  style="Hint.TLabel").pack(anchor="w", padx=16, pady=(2, 8))

    def file_pick(self):
        path = filedialog.askopenfilename(
            title="选择文件",
            filetypes=[("支持格式", "*.docx *.pdf *.png *.jpg *.jpeg"),
                       ("Word", "*.docx"), ("PDF", "*.pdf"),
                       ("图片", "*.png *.jpg *.jpeg"), ("所有文件", "*.*")]
        )
        if path:
            self.file_path.set(path)
            self.file_result_show(f"已选择：{path}\n" + self._file_guess(path))

    def file_result_show(self, msg, color="#333333"):
        self.file_result.config(state="normal")
        self.file_result.delete("1.0", "end")
        self.file_result.insert("1.0", msg)
        self.file_result.config(fg=color)
        self.file_result.config(state="disabled")

    def _file_guess(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".docx":
            return "检测为 Word 文档：水印以隐藏字符嵌入正文，Word 可继续编辑。"
        if ext == ".pdf":
            return "检测为 PDF：水印以透明文本层写入每页，不影响阅读。"
        if ext in (".png", ".jpg", ".jpeg"):
            return "检测为图片：水印为频域盲水印，肉眼不可见。"
        return "（格式提示：推荐 .docx / .pdf / .png / .jpg）"

    def file_embed(self):
        path = self.file_path.get().strip()
        wm = self.file_wm.get().strip()
        pwd = self.file_pwd.get()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("提示", "请先选择要嵌入水印的文件")
            return
        if not wm:
            messagebox.showwarning("提示", "请输入水印内容")
            return
        if not pwd:
            messagebox.showwarning("提示", "请输入密码")
            return
        try:
            out = embed_file(path, wm, pwd)
            self.file_result_show(
                f"嵌入成功 ✓\n\n输出文件：{out}\n"
                f"水印：{wm}\n\n原文件未被修改，可分发 _wm 副本用于溯源。",
                "#16a34a")
        except Exception as e:
            self.file_result_show(f"嵌入失败 ✗\n{e}", "#dc2626")

    def file_extract(self):
        path = self.file_path.get().strip()
        pwd = self.file_pwd.get()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("提示", "请先选择要提取水印的文件")
            return
        if not pwd:
            messagebox.showwarning("提示", "请输入密码")
            return
        try:
            result = extract_file(path, pwd)
            if result is not None:
                self.file_result_show(f"提取成功 ✓\n\n水印内容：{result}", "#16a34a")
            else:
                self.file_result_show(
                    "未检测到有效水印，或密码错误，或文件被深度篡改。\n"
                    "提示：图片请尽量选择未经压缩的原图；Word/PDF 需为嵌入过水印的副本。",
                    "#dc2626")
        except Exception as e:
            self.file_result_show(f"提取失败 ✗\n{e}", "#dc2626")

    def _build_about_tab(self, notebook):
        tab = ttk.Frame(notebook)
        frm = ttk.Frame(tab)
        frm.pack(fill="both", expand=True, padx=20, pady=20)

        ttk.Label(frm, text="隐水印工具（文本 / Word / PDF / 图片）", style="Title.TLabel").pack(anchor="w")
        info_text = (
            "\n"
            "在文本与文档中嵌入肉眼不可见的水印信息，用于文档溯源和版权保护。\n\n"
            "功能：\n"
            "  · 文本嵌入/提取 — 纯文本中嵌入零宽字符水印\n"
            "  · 文件水印 — Word(.docx)/PDF(.pdf)/图片(.png .jpg) 直接嵌水印\n"
            "    生成 _wm 副本，原文件不变；提取需相同密码\n\n"
            "原理：\n"
            "  · 文本/Word — 零宽 Unicode 字符承载加密水印\n"
            "  · PDF — 每页写入透明文本层（肉眼不可见、可再处理）\n"
            "  · 图片 — 全网格 8×8 DCT 频域盲水印\n"
            "    抗裁剪（网格相位+循环移位恢复）、抗等比放大、抗重压缩\n\n"
            "安全与抗破坏特性：\n"
            "  · PBKDF2-HMAC-SHA256 密钥派生（10万次迭代）\n"
            "  · HMAC-SHA256-CTR 流加密 + CRC16 完整性校验\n"
            "  · 文本引擎双方案冗余：位置编码 + Reed-Solomon 纠删码\n"
            "    抗「零宽字符被随机剥离」；多份完整副本 + 8 偏移\n"
            "    重同步，抗「文本被截断 / 编辑」\n"
            "  · 实测（1500 字以上文本）：均匀随机剥离 30%、\n"
            "    连续删除 40%、局部清除 50% 均可完整提取\n"
            "  · 图片实测：JPEG q85 重压缩、任意位置裁剪、等比放大\n"
            "    （1.5x/2.0x）后仍可提取（PSNR ≈ 32dB）\n\n"
            "注意：\n"
            "  · 文本越短、水印越长，可存放的冗余越少，抗破坏能力相应下降\n"
            "  · 图片等比缩小（0.75x 及以下，信息有损）与旋转暂不抵抗；\n"
            "    提取建议用无压缩原图最准（v2 通过网格相位搜索可容忍裁剪）\n\n"
            "兼容平台：\n"
            "  微信、钉钉、Chrome、记事本、Word、常见 PDF 阅读器等均不可见\n"
        )
        lbl = tk.Label(frm, text=info_text, justify="left", anchor="w",
                       font=("Microsoft YaHei UI", 10), bg="#f5f5f5", fg="#444444")
        lbl.pack(anchor="w")

        return tab

    # ── 嵌入操作 ──────────────────────────────

    def do_embed(self):
        text = self.embed_text.get("1.0", "end-1c")
        wm = self.wm_var.get().strip()
        pwd = self.pwd_embed.get()

        if not text:
            messagebox.showwarning("提示", "请输入文本内容")
            return
        if not wm:
            messagebox.showwarning("提示", "请输入水印内容")
            return
        if not pwd:
            messagebox.showwarning("提示", "请输入密码")
            return

        twm = TextWatermark(password=pwd)
        pos = self.pos_var.get()
        if pos == "first":
            result = twm.add_wm_at_first(text, wm)
        elif pos == "last":
            result = twm.add_wm_at_last(text, wm)
        else:
            result = twm.add_wm_rnd(text, wm)

        self.embed_text.delete("1.0", "end")
        self.embed_text.insert("1.0", result)

        zwm_count = TextWatermark.count_zwm(result)
        visible_match = text == TextWatermark.remove_watermark(result)
        self.embed_status.set(f"嵌入成功 | 隐藏字符: {zwm_count} | 文本看起来一致: {visible_match}")

    def embed_import(self):
        path = filedialog.askopenfilename(
            title="选择文本文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.embed_text.delete("1.0", "end")
                    self.embed_text.insert("1.0", f.read())
                self.embed_status.set(f"已导入: {path}")
            except Exception as e:
                messagebox.showerror("错误", f"读取失败: {e}")

    def embed_export(self):
        text = self.embed_text.get("1.0", "end-1c")
        if not text:
            messagebox.showwarning("提示", "文本为空")
            return
        path = filedialog.asksaveasfilename(
            title="保存文件",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.embed_status.set(f"已保存: {path}")
                messagebox.showinfo("成功", f"文件已保存到:\n{path}")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {e}")

    def embed_clear(self):
        self.embed_text.delete("1.0", "end")
        self.wm_var.set("")
        self.pwd_embed.set("")
        self.embed_status.set("已清空")

    # ── 提取操作 ──────────────────────────────

    def do_extract(self):
        text = self.extract_text.get("1.0", "end-1c")
        pwd = self.pwd_extract.get()

        if not text:
            messagebox.showwarning("提示", "请输入文本内容")
            return
        if not pwd:
            messagebox.showwarning("提示", "请输入密码")
            return

        twm = TextWatermark(password=pwd)
        result = twm.extract(text)

        if result is not None:
            self.result_label.config(text=result, fg="#16a34a")
            self.result_stats.set("提取成功")
        else:
            self.result_label.config(text="（未检测到有效水印或密码错误）", fg="#dc2626")
            self.result_stats.set("")

    def do_check(self):
        text = self.extract_text.get("1.0", "end-1c")
        if not text:
            messagebox.showwarning("提示", "请输入文本内容")
            return
        has_wm = TextWatermark.has_watermark(text)
        count = TextWatermark.count_zwm(text)
        if has_wm:
            self.result_label.config(text=f"检测到隐藏水印", fg="#2563eb")
            self.result_stats.set(f"零宽字符数: {count} | 预估数据量: {count // 8} 字节")
        else:
            self.result_label.config(text="未检测到隐藏水印", fg="#888888")
            self.result_stats.set("")

    def do_remove(self):
        text = self.extract_text.get("1.0", "end-1c")
        if not text:
            messagebox.showwarning("提示", "请输入文本内容")
            return
        clean = TextWatermark.remove_watermark(text)
        self.extract_text.delete("1.0", "end")
        self.extract_text.insert("1.0", clean)
        self.result_label.config(text="水印已清除", fg="#16a34a")
        self.result_stats.set("")

    def extract_import(self):
        path = filedialog.askopenfilename(
            title="选择文本文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.extract_text.delete("1.0", "end")
                    self.extract_text.insert("1.0", f.read())
            except Exception as e:
                messagebox.showerror("错误", f"读取失败: {e}")

    def extract_clear(self):
        self.extract_text.delete("1.0", "end")
        self.pwd_extract.set("")
        self.result_label.config(text="（等待提取）", fg="#2563eb")
        self.result_stats.set("")

    def _update_stats(self):
        pass


def main():
    root = tk.Tk()
    app = WatermarkApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
