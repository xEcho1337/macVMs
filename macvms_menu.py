import os
import rumps
import subprocess
from macvms_pkg.cli import get_vms, start_vm_noninteractive, stop_vm, is_vm_running


class MacVMsApp(rumps.App):
    def __init__(self):
        super(MacVMsApp, self).__init__("macVMs", icon=None, quit_button=None)
        self.menu = ["VMs", None]
        self.update_menu()

    def update_menu(self):
        # Clear existing VM items
        self.menu.clear()
        self.menu.add(rumps.MenuItem("VMs", callback=None))
        self.menu.add(rumps.separator)

        vms = get_vms()
        for vm in sorted(vms):
            status = is_vm_running(vm)
            if status == "running":
                icon = "🟢"
            elif status == "booting":
                icon = "🟠"
            else:
                icon = "🔴"
            item = rumps.MenuItem(f"{icon} {vm}", callback=self.toggle_vm)
            item.vm_name = vm
            self.menu.add(item)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Refresh", callback=self.refresh_menu))
        self.menu.add(rumps.MenuItem("Close macVMs", callback=self.quit_app))
        self.menu.add(rumps.MenuItem("Open in Terminal", callback=self.open_terminal))
        self.menu.add(rumps.MenuItem("Open macVMs folder", callback=self.open_folder))

    def toggle_vm(self, sender):
        vm_name = sender.vm_name
        if is_vm_running(vm_name):
            stop_vm(vm_name)
        else:
            start_vm_noninteractive(vm_name)
        self.update_menu()

    def refresh_menu(self, _):
        self.update_menu()

    def quit_app(self, _):
        rumps.quit_application()

    def open_terminal(self, _):
        cwd = os.getcwd()
        script = f'tell application "Terminal" to do script "cd {cwd} && python macvms.py --cli"'
        subprocess.run(["osascript", "-e", script])

    def open_folder(self, _):
        folder = os.path.expanduser("~/macVMs")
        subprocess.run(["open", folder])


if __name__ == "__main__":
    MacVMsApp().run()