"""生成 CmdGauge 应用图标 (圆角渐变底 + 终端提示符, 多尺寸 ICO).

运行: python scripts/build_icon.py -> 输出 assets/CmdGauge.ico
"""
import os

from PIL import Image, ImageDraw

VIEW = 48
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "CmdGauge.ico")

# 与 app/web/logo-final.svg 保持一致的渐变端点
C_FROM = (59, 130, 246)   # #3b82f6
C_TO = (6, 182, 212)      # #06b6d4


def _lerp(a: int, b: int, k: float) -> int:
    return int(round(a + (b - a) * k))


def draw_logo(size: int) -> Image.Image:
    ss = 4  # 超采样倍率 (画圆角与斜线更平滑)
    w = size * ss
    img = Image.new("RGBA", (w, w), (0, 0, 0, 0))

    # 对角渐变: 按 (x+y) 线性插值
    grad = Image.new("RGBA", (w, w))
    px = grad.load()
    for y in range(w):
        for x in range(w):
            k = (x + y) / (2 * (w - 1)) if w > 1 else 0.0
            px[x, y] = (_lerp(C_FROM[0], C_TO[0], k), _lerp(C_FROM[1], C_TO[1], k),
                        _lerp(C_FROM[2], C_TO[2], k), 255)

    # 圆角方形遮罩 (reduction 缩放会自带抗锯齿)
    mask = Image.new("L", (w, w), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, w - 1, w - 1], radius=int(w * 8.5 / 32), fill=255
    )
    img.paste(grad, (0, 0), mask)

    if size >= 32:
        d = ImageDraw.Draw(img)
        u = w / 32.0  # 以 32 视图为单位
        lw = max(2, int(round(2.4 * u)))
        # 提示符 ">"
        d.line([(10.2 * u, 11.4 * u), (14.4 * u, 16 * u), (10.2 * u, 20.6 * u)],
               fill=(255, 255, 255, 255), width=lw, joint="curve")
        # 下划线
        d.line([(16.8 * u, 20.6 * u), (22 * u, 20.6 * u)],
               fill=(255, 255, 255, 255), width=lw)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base = draw_logo(256)
    base.save(OUT, format="ICO", sizes=sizes)
    chk = Image.open(OUT)
    print("written:", os.path.abspath(OUT))
    print("ico sizes:", sorted(getattr(chk, "info", {}).get("sizes") or []), "| fmt:", chk.format)


if __name__ == "__main__":
    main()
