#!/bin/bash
set -e

echo "[macVMs] Setting up macvms command..."

if [ ! -f "$HOME/.ssh/id_ed25519" ]; then
    echo "[macVMs] Generating SSH key..."
    ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519" -N ""
else
    echo "[macVMs] SSH key already exists, skipping..."
fi

read -p "VM IP/Host [localhost]: " VM_HOST
VM_HOST=${VM_HOST:-localhost}

if [ "$VM_HOST" = "localhost" ]; then
    DEFAULT_PORT=2222
else
    DEFAULT_PORT=22
fi

read -p "SSH Port [$DEFAULT_PORT]: " VM_PORT
VM_PORT=${VM_PORT:-$DEFAULT_PORT}

echo "[macVMs] Copying SSH key to VM..."
ssh-copy-id -p "$VM_PORT" root@"$VM_HOST" || true

CMD_PATH="/usr/local/bin/macvms"

echo "[macVMs] Creating macvms command at $CMD_PATH..."

sudo tee "$CMD_PATH" > /dev/null << EOF
#!/bin/bash

HOST_DIR="\$PWD"
VM_DIR="/mnt/shared\${HOST_DIR}"

VM_HOST="$VM_HOST"
VM_PORT="$VM_PORT"

ssh -t root@"\$VM_HOST" -p "\$VM_PORT" "cd '\$VM_DIR' 2>/dev/null || cd /mnt/shared; exec \\\$SHELL -l"
EOF

sudo chmod +x "$CMD_PATH"

echo "[macVMs] Done! Now you can use 'macvms' from anywhere."