"""验证 dist_v2/TextWatermark.exe：版本元数据 + 启动冒烟"""
import ctypes, struct, subprocess, sys, time

EXE = r"D:/desktop/text_watermark/dist/TextWatermark.exe"
ok = True

# ── 1. 版本元数据（杀软按访问扫描可能瞬时锁文件 → 重试） ──────
h = 0
for attempt in range(6):
    h = ctypes.windll.version.GetFileVersionInfoSizeW(EXE, None)
    if h:
        break
    time.sleep(3)
assert h, "GetFileVersionInfoSizeW 失败（多次重试仍无法读取，可能被占用）"
buf = ctypes.create_string_buffer(h)
assert ctypes.windll.version.GetFileVersionInfoW(EXE, 0, h, buf), "GetFileVersionInfoW 失败"

def query(name):
    ptr = ctypes.c_void_p()
    ln = ctypes.c_uint()
    sub = r"\StringFileInfo\080404B0" + "\\" + name
    if not ctypes.windll.version.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(ln)):
        return None
    return ctypes.wstring_at(ptr.value)   # 读到 null 结束，避免长度单位误判

want = {
    "CompanyName": "BrainAI",
    "ProductName": "文本隐水印工具",
    "FileVersion": "1.0.0.0",
    "ProductVersion": "1.0.0.0",
}
print("== 版本元数据 ==")
for k, exp in want.items():
    got = query(k)
    status = "PASS" if got == exp else "FAIL"
    if got != exp:
        ok = False
    print(f"  [{status}] {k} = {got!r} (期望 {exp!r})")

# ── 2. 启动冒烟：进程能拉起且存活几秒（不立即崩溃） ──────
print("\n== 启动冒烟 ==")
proc = subprocess.Popen([EXE])
time.sleep(5)
alive = proc.poll() is None
if alive:
    print("  [PASS] 启动后进程存活（GUI 已拉起，无立即崩溃）")
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
else:
    print(f"  [FAIL] 进程提前退出 code={proc.returncode}")
    ok = False

print("\n=====", "全部 PASS" if ok else "存在 FAIL", "=====")
sys.exit(0 if ok else 1)
