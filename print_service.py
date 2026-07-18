"""
Handles sending a barcode label to the physical printer.

Right now there's no printer connected, so print_label() just confirms the
label image exists on disk and returns False (nothing was actually printed).

Once the USB printer arrives, uncomment the real implementation below.
Most small USB label printers (Xprinter, Munbyn, etc.) install a normal
Windows/Mac driver, so this becomes a standard OS print call - no barcode
SDK or protocol work needed.
"""

import os

BARCODE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "barcodes")

# Set this once you know the exact printer name Windows/Mac shows for it.
# On Windows: Settings > Printers & scanners, copy the exact name.
# On Mac: System Settings > Printers & Scanners, copy the exact name.
PRINTER_NAME = None  # e.g. "XP-365B"


def print_label(barcode_value: str) -> bool:
    """
    Sends the label image for `barcode_value` to the printer.
    Returns True if a real print job was sent, False if only stubbed/logged.
    """
    image_path = os.path.join(BARCODE_DIR, f"{barcode_value}.png")

    if not os.path.exists(image_path):
        print(f"[print_service] No label image found for {barcode_value} at {image_path}")
        return False

    if PRINTER_NAME is None:
        # --- STUB MODE (no printer connected yet) ---
        print(f"[print_service] STUB: would print {barcode_value} "
              f"-> label saved at {image_path}. Set PRINTER_NAME to enable real printing.")
        return False

    # --- REAL PRINTING (uncomment once PRINTER_NAME is set) ---
    #
    # Windows (requires: pip install pywin32):
    #
    # import win32print
    # import win32ui
    # from PIL import Image, ImageWin
    #
    # img = Image.open(image_path)
    # hprinter = win32print.OpenPrinter(PRINTER_NAME)
    # try:
    #     hdc = win32ui.CreateDC()
    #     hdc.CreatePrinterDC(PRINTER_NAME)
    #     hdc.StartDoc(barcode_value)
    #     hdc.StartPage()
    #     dib = ImageWin.Dib(img)
    #     dib.draw(hdc.GetHandleOutput(), (0, 0, img.width, img.height))
    #     hdc.EndPage()
    #     hdc.EndDoc()
    # finally:
    #     win32print.ClosePrinter(hprinter)
    # return True
    #
    # Mac/Linux (uses CUPS, already on the OS - no extra install):
    #
    # import subprocess
    # result = subprocess.run(
    #     ["lp", "-d", PRINTER_NAME, image_path],
    #     capture_output=True, text=True
    # )
    # return result.returncode == 0

    return False
