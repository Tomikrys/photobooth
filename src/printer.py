import platform, subprocess
from pathlib import Path
from PIL import Image


def print_image(filepath: str, printer_name: str, copies: int = 1) -> None:
    if not printer_name:
        raise ValueError("PRINTER_NAME is not configured — set it in /config")
    if platform.system() == "Windows":
        _print_windows(filepath, printer_name, copies)
    else:
        _print_mac(filepath, printer_name, copies)


def _print_mac(filepath: str, printer_name: str, copies: int) -> None:
    for _ in range(copies):
        result = subprocess.run(
            ["lp", "-d", printer_name, filepath],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Print failed: {result.stderr}")


def _print_windows(filepath: str, printer_name: str, copies: int) -> None:
    import win32print, win32ui
    from PIL import ImageWin

    printer_handle = win32print.OpenPrinter(printer_name)
    try:
        dc = win32ui.CreateDC()
        dc.CreatePrinterDC(printer_name)

        img = Image.open(filepath).convert("RGB")
        printable_w = dc.GetDeviceCaps(8)   # HORZRES
        printable_h = dc.GetDeviceCaps(10)  # VERTRES

        img_w, img_h = img.size
        scale = min(printable_w / img_w, printable_h / img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        x_offset = (printable_w - new_w) // 2
        y_offset = (printable_h - new_h) // 2

        for _ in range(copies):
            dc.StartDoc(Path(filepath).name)
            dc.StartPage()
            dib = ImageWin.Dib(img)
            dib.draw(dc.GetSafeHdc(), (x_offset, y_offset, x_offset + new_w, y_offset + new_h))
            dc.EndPage()
            dc.EndDoc()
    finally:
        win32print.ClosePrinter(printer_handle)
        dc.DeleteDC()
