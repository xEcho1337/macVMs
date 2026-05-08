# macVMs

macVMs is a small CLI tool to manage QEMU virtual machines.
It is designed to simplify the creation and usage of fully emulated x86 and x86_64 VMs on ARM-based MacBooks.

The interface is interactive and menu-driven, so no manual QEMU commands are required.

## Features

* Automatic ISO download
* VM creation with configurable RAM, CPU and disk
* Start, inspect and delete VMs
* Fully headless install path for serial-only terminals
* Optional shared folder (host ↔ guest via 9p)
* Per-VM QEMU overrides via `qemu.conf`
* Networking presets for `user`, `vmnet-shared`, and `vmnet-bridged`

The tool focuses on being minimal and predictable rather than feature-rich.

## Installation

Requirements:

* VM/OS installation knowledge
* Python 3.9+
* QEMU (`qemu-system-x86_64`, `qemu-img`)

Clone the repository:

```bash
git clone https://github.com/xEcho1337/macVMs
```

Install QEMU (macOS):

```bash
brew install qemu
```

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Run the tool:

```bash
python macvms.py
```

Follow the interactive menu to create and manage VMs.

## Creating a VM

During setup you will choose:

* VM name
* Operating system (Debian, Ubuntu)
* RAM, CPU cores, disk size
* Optional shared folder

The tool will automatically:

1. Download the ISO (if needed)
2. Create a QCOW2 disk
3. Start the installer

The installer now boots directly on the serial console in headless mode.

Ubuntu is started in serial-friendly installer mode too. When the installer reaches the final "remove installation medium" prompt, `macVMs` closes the temporary install session automatically so you can boot the installed system cleanly with `Start VM`.

Each VM also gets a per-VM `qemu.conf` file inside its folder. Existing VMs keep working even if that file is missing.

## Recommended setup

For a lightweight VM, avoid installing a graphical environment.

At the *software selection* step:

* Keep only **standard system utilities**
* Do not select any desktop environment (GNOME, KDE, etc.)

This results in a minimal system that boots directly into a terminal.

## Shared folders

If configured, a host directory is exposed to the VM using QEMU 9p.

Inside the guest, mount it manually:

```bash
sudo mkdir /mnt/shared
sudo mount -t 9p -o trans=virtio shared /mnt/shared
```

To automatically mount at each startup:

```bash
sudo mkdir /mnt/shared
echo 'shared /mnt/shared 9p trans=virtio,version=9p2000.L,rw 0 0' | sudo tee -a /etc/fstab
sudo mount -a
```

The mount point can be changed as needed.

## Advanced QEMU options

Each VM can be customized with `~/macVMs/vms/<vm-name>/qemu.conf`.

Supported keys:

* `network=user|vmnet-shared|vmnet-bridged`
* `ifname=<host interface>` for `vmnet-bridged`
* `nic_model=<qemu nic model>` such as `e1000` or `virtio-net-pci`
* `hostfwd=<forward rules>` for `network=user`
* `extra_args=<raw QEMU args appended to the command>`
* `qemu_args=<raw QEMU args appended to the command>`

Default behavior stays compatible with older VMs:

```ini
network=user
```

Example using a managed preset and a custom NIC:

```ini
network=vmnet-shared
extra_args=-device virtio-net-pci,netdev=net0
```

Example with fully raw networking arguments:

```ini
qemu_args=-netdev vmnet-shared,id=net0 -device virtio-net-pci,netdev=net0
```

Example bridged configuration:

```ini
network=vmnet-bridged
ifname=en0
nic_model=virtio-net-pci
```

For `network=user`, port forwards can be overridden with semicolon-separated entries:

```ini
network=user
hostfwd=tcp::2222-:22;tcp::8080-:80
```

Notes:

* `qemu_args` and `extra_args` are intentionally flexible and are only lightly validated.
* If your raw arguments already define `-netdev`, `-nic`, or a `-device ... netdev=...`, macVMs will avoid adding its default managed network arguments on top.
* `vmnet-bridged` requires a compatible host interface name such as `en0`.
* `vmnet-*` support requires a QEMU build with vmnet enabled. Upstream QEMU documents `vmnet-shared` and `vmnet-bridged` starting from QEMU 7.1.

When `vmnet-shared` or `vmnet-bridged` is used, macVMs will try to detect and print the guest IP address from the macOS DHCP lease database after boot.

## Remote connection

This step is optional but recommended for a smoother workflow.

You can setup a remote connection to the VM for faster access, similar to **WSL**.

- `scripts/install-macvms.sh` - Adds the `macvms` command to your terminal for instant login
- `scripts/setup-ssh.sh` - Sets up SSH keys to avoid entering the password each time (included in the previous command)

#### Prerequisites
1. A working VM obviously
2. Install and enable SSH inside the VM
3. Set a password for the root account
4. Allow root login via SSH

With the default `user` networking preset, SSH forwarding remains on `localhost:2222` unless changed in `qemu.conf`.

## Notes

* Uses QEMU in full emulation mode (TCG)
* No hardware virtualization required
* Lower performance is expected compared to native virtualization

## Scope

macVMs is intended for simple and reproducible VM setups, such as Cybersecurity environments, testing and development.

**Note: It is not intended to replace full virtualization platforms.**

## License

macVMs is maintained by xEcho1337 and is licensed under the Apache License, Version 2.0.
