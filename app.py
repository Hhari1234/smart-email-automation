"""
app.py
Entry point for ResumeMailer.

Run with:
    python app.py
"""
import tkinter as tk
from gui import ResumeMailerApp


def main():
    root = tk.Tk()
    app = ResumeMailerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
