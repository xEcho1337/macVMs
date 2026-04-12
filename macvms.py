import sys
from macvms_pkg.cli import menu
from macvms_menu import MacVMsApp

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        menu()
    else:
        MacVMsApp().run()
