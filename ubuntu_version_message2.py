import platform
from tkinter import messagebox
import time


def check_ubuntu_version():
    if platform.system() == "Linux" and platform.dist()[0] == "Ubuntu" and platform.dist()[1] == "22.04":
        return True
    return False


def show_popup_message():
    if not check_ubuntu_version():
        message = "You are running an unsupported OS.\nPlease upgrade to Ubuntu 22.04."
        messagebox.showwarning("Unsupported OS", message)


if __name__ == "__main__":
    while True:
        show_popup_message()
        time.sleep(1800)  # Wait for 30 minutes
