#!/bin/bash
read -p "VM IP/Host [localhost]: " VM_HOST
VM_HOST=${VM_HOST:-localhost}

if [ "$VM_HOST" = "localhost" ]; then
    DEFAULT_PORT=2222
else
    DEFAULT_PORT=22
fi

read -p "SSH Port [$DEFAULT_PORT]: " VM_PORT
VM_PORT=${VM_PORT:-$DEFAULT_PORT}

ssh-keygen -t ed25519
ssh-copy-id -p "$VM_PORT" root@"$VM_HOST"