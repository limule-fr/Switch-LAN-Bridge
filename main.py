import tkinter as tk
from core.diagnostics import run_diagnostics
from gui.window import SLBWindow

def main():
    root = tk.Tk()
    app = SLBWindow(root, run_diagnostics)
    root.mainloop()

if __name__ == "__main__":
    main()
