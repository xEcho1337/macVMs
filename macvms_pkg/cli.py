import os
import shutil
import subprocess
import time
import urllib.request

import psutil

import logging
logging.basicConfig(filename=os.path.expanduser("~/macVMs/macvms.log"), level=logging.ERROR)

from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from .config import ISOS, VM_DIR, config_path, load_config, save_config, vm_path
from .qemu import (
    build_install_qemu_cmd,
    build_start_qemu_cmd,
    has_persistent_serial_support,
    stream_interactive_process,
)
from .ui import BANNER, console


def ask_int(prompt_text, default):
    value = console.input(f"[bold]{prompt_text}[/bold] [dim](default: {default})[/dim]: ").strip()
    if value == "":
        return default
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except ValueError:
        console.print("[red]Invalid number, using default[/red]")
        return default


def is_valid_vm_name(name):
    return (
        bool(name)
        and name not in {".", ".."}
        and os.path.basename(name) == name
        and "/" not in name
        and "\\" not in name
    )


def download_iso(os_name):
    iso = ISOS[os_name]
    path = iso["file"]

    if os.path.exists(path) and os.path.getsize(path) > 0:
        console.print("[green]ISO already present[/green]")
        return

    console.print("[cyan]Downloading ISO...[/cyan]")

    request = urllib.request.Request(
        iso["url"],
        headers={"User-Agent": "Mozilla/5.0"},
    )

    with urllib.request.urlopen(request) as response:
        total_size = int(response.headers.get("Content-Length", 0))
        os.makedirs(os.path.dirname(path), exist_ok=True)

        with open(path, "wb") as out_file, Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Downloading",
                total=total_size if total_size > 0 else None,
            )

            downloaded = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break

                out_file.write(chunk)
                downloaded += len(chunk)

                if total_size > 0:
                    progress.update(task, completed=downloaded)
                else:
                    progress.update(task, advance=len(chunk))

    console.print("[green]Download completed[/green]")


def install_vm():
    name = console.input("[bold]VM name:[/bold] ").strip()
    if not is_valid_vm_name(name):
        console.print("[red]Invalid VM name[/red]")
        return

    os_name = console.input(f"[bold]OS ({'/'.join(ISOS.keys())}):[/bold] ").strip().lower()
    if os_name not in ISOS:
        console.print("[red]Unsupported OS[/red]")
        return

    ram = ask_int("RAM (MB)", 4096)
    cpu = ask_int("CPU cores", 4)
    disk_size = ask_int("Disk size (GB)", 20)

    shared_path = console.input("[bold]Host shared folder path (empty = none):[/bold] ").strip()

    if shared_path == "":
        shared_path = None
    else:
        shared_path = os.path.abspath(shared_path)
        if not os.path.exists(shared_path):
            console.print(f"[yellow]Creating shared folder at {shared_path}[/yellow]")
            os.makedirs(shared_path, exist_ok=True)

    path = vm_path(name)
    if os.path.exists(path):
        console.print("[red]VM already exists[/red]")
        return

    os.makedirs(path, exist_ok=True)
    disk = os.path.join(path, "disk.qcow2")

    download_iso(os_name)

    console.print("[cyan]Creating disk...[/cyan]")
    result = subprocess.run(
        ["qemu-img", "create", "-f", "qcow2", disk, f"{disk_size}G"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print("[red]Failed to create disk image[/red]")
        if result.stderr:
            console.print(f"[red]{result.stderr.strip()}[/red]")
        return

    config = {
        "name": name,
        "os": os_name,
        "ram": ram,
        "cpu": cpu,
        "disk": "disk.qcow2",
        "disk_size_gb": disk_size,
        "created_at": time.ctime(),
        "shared_folder": shared_path,
        "serial_bootstrap_version": 1,
    }
    save_config(name, config)

    console.print("[green]Starting installer...[/green]")
    if shared_path:
        console.print("[yellow]Shared folder is attached as 9p tag 'shared'.[/yellow]")
        console.print("[yellow]Mount it inside the guest OS after installation if needed.[/yellow]")

    try:
        qemu_cmd = build_install_qemu_cmd(name, os_name, ram, cpu, disk, shared_path)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return
    
    console.print("[cyan]Installer will boot directly on the serial console.[/cyan]")
    console.print("[cyan]At the end of installation, macVMs will close the temporary install session automatically.[/cyan]")
    returncode, completed_install = stream_interactive_process(
        qemu_cmd,
        stop_text="Please remove the installation medium, then press ENTER:"
    )
    if completed_install:
        console.print("[green]Installation session closed.[/green]")
        console.print("[bold]Next step:[/bold] return to the menu and choose [bold]Start VM[/bold].")
    elif returncode not in {0, -15}:
        console.print(f"[red]Installer exited with code {returncode}.[/red]")


def list_vms():
    vms = [vm for vm in os.listdir(VM_DIR) if os.path.isdir(vm_path(vm))]

    table = Table(title="VMs")
    table.add_column("Name", style="cyan")
    table.add_column("OS")
    table.add_column("RAM")
    table.add_column("CPU")
    table.add_column("Disk (GB)")
    table.add_column("Shared")

    if not vms:
        console.print("[yellow]No VMs found[/yellow]")
        return

    for vm in sorted(vms):
        try:
            cfg = load_config(vm)
            table.add_row(
                cfg.get("name", vm),
                str(cfg.get("os", "?")),
                str(cfg.get("ram", "?")),
                str(cfg.get("cpu", "?")),
                str(cfg.get("disk_size_gb", "?")),
                "Yes" if cfg.get("shared_folder") else "No",
            )
        except Exception:
            table.add_row(vm, "?", "?", "?", "?", "?")

    console.print(table)


def info_vm():
    name = console.input("[bold]VM name:[/bold] ").strip()

    if not is_valid_vm_name(name) or not os.path.exists(config_path(name)):
        console.print("[red]VM not found[/red]")
        return

    data = load_config(name)

    table = Table(title=f"VM Info: {name}")
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    for k, v in data.items():
        table.add_row(k, str(v))

    console.print(table)


def start_vm():
    name = console.input("[bold]VM name:[/bold] ").strip()

    if not is_valid_vm_name(name) or not os.path.exists(config_path(name)):
        console.print("[red]VM not found[/red]")
        return

    config = load_config(name)
    disk = os.path.join(vm_path(name), config["disk"])

    if not os.path.exists(disk):
        console.print("[red]Disk image not found[/red]")
        return

    console.print("[green]Starting VM...[/green]")
    if config.get("shared_folder"):
        console.print("[yellow]Shared folder is attached as 9p tag 'shared'.[/yellow]")
        console.print("[yellow]Mount it inside the guest if you need it.[/yellow]")

    subprocess.run(build_start_qemu_cmd(config, disk))


def delete_vm():
    name = console.input("[bold]VM name:[/bold] ").strip()

    if not is_valid_vm_name(name):
        console.print("[red]Invalid VM name[/red]")
        return

    path = vm_path(name)
    if not os.path.exists(path):
        console.print("[red]VM not found[/red]")
        return

    confirm = console.input("[red]Delete VM? (y/n):[/red] ").strip().lower()
    if confirm != "y":
        return

    shutil.rmtree(path)
    console.print("[green]VM deleted[/green]")


def get_vms():
    return [vm for vm in os.listdir(VM_DIR) if os.path.isdir(vm_path(vm))]


def start_vm_noninteractive(name):
    if not is_valid_vm_name(name) or not os.path.exists(config_path(name)):
        logging.error(f"VM {name}: invalid name or config not found")
        return False

    config = load_config(name)
    disk = os.path.join(vm_path(name), config["disk"])

    if not os.path.exists(disk):
        logging.error(f"VM {name}: disk not found at {disk}")
        return False

    try:
        cmd = build_start_qemu_cmd(config, disk)
        logging.info(f"Starting VM {name} with cmd: {cmd}")
        subprocess.Popen(cmd)
        return True
    except Exception as e:
        logging.error(f"Failed to start VM {name}: {e}")
        return False


def stop_vm(name):
    # To stop a VM, we need to find the QEMU process and kill it
    # This is a simple implementation; in a real app, you'd track PIDs
    import psutil
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        if proc.info['name'] == 'qemu-system-x86_64':
            cmdline = proc.info['cmdline']
            if cmdline and any(name in arg for arg in cmdline):
                proc.kill()
                return True
    return False


def is_vm_running(name):
    import psutil
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        if proc.info['name'] == 'qemu-system-x86_64':
            cmdline = proc.info['cmdline']
            if cmdline and any(name in arg for arg in cmdline):
                # Se creato meno di 30 secondi fa, è booting
                if time.time() - proc.create_time() < 30:
                    return "booting"
                else:
                    return "running"
    return "stopped"


def menu():
    while True:
        console.clear()
        console.print(Panel(BANNER))

        table = Table(show_header=False)
        table.add_row("0", "Exit")
        table.add_row("1", "Install VM")
        table.add_row("2", "List VMs")
        table.add_row("3", "Start VM")
        table.add_row("4", "VM Info")
        table.add_row("5", "Delete VM")

        console.print(table)

        choice = console.input("\n[bold]> [/bold]").strip()


        if choice == "0":
            break
        elif choice == "1":
            install_vm()
        elif choice == "2":
            list_vms()
        elif choice == "3":
            start_vm()
        elif choice == "4":
            info_vm()
        elif choice == "5":
            delete_vm()
        else:
            console.print("[red]Invalid option[/red]")

        console.input("\n[dim]Press Enter to continue...[/dim]")
