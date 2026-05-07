#!/usr/bin/env bash
set -euo pipefail

MARKER_BEGIN="### BEGIN SAMBA SHARES SUITE"
MARKER_END="### END SAMBA SHARES SUITE"

detect_shell() {
  local shname
  shname=$(basename "${SHELL:-}")
  if [[ -z "$shname" ]]; then
    shname=$(ps -p $$ -o comm= 2>/dev/null || echo sh)
  fi
  echo "$shname"
}

shell_name=$(detect_shell)
case "$shell_name" in
  bash|sh)
    cfg="$HOME/.bashrc"
    ;;
  zsh)
    cfg="$HOME/.zshrc"
    ;;
  fish)
    echo "Detected fish shell; this installer supports bash/zsh only."
    echo "Please add the Samba functions manually to $HOME/.config/fish/config.fish"
    exit 1
    ;;
  *)
    if [[ -f "$HOME/.bashrc" ]]; then
      cfg="$HOME/.bashrc"
    else
      cfg="$HOME/.profile"
    fi
    ;;
esac

echo "Detected shell: $shell_name"
echo "Target config file: $cfg"

mkdir -p "$(dirname "$cfg")"
touch "$cfg"

if grep -Fq "$MARKER_BEGIN" "$cfg"; then
  echo "Samba suite already present in $cfg — nothing to do." 
  exit 0
fi

bak="$cfg.backup.$(date +%Y%m%d%H%M%S)"
cp "$cfg" "$bak"
echo "Backed up existing config to: $bak"

cat >> "$cfg" <<'EOF'

### BEGIN SAMBA SHARES SUITE

# --- Final Samba Management Suite ---

# 1. Start Samba with Status and All Local IPs
share-on() {
    echo -e "\e[33mStarting Samba services...\e[0m"
    sudo systemctl start smb nmb
    
    echo -e "\e[32mSamba is now ON\e[0m"
    
    # Grabs all active IPv4 addresses, excluding the loopback (127.0.0.1)
    echo -e "\e[34mAvailable Connection IPs:\e[0m"
    ip -4 addr show | grep -v "127.0.0.1" | grep "inet " | awk '{print "  ➜ " $NF ": " $2}' | cut -d/ -f1
}

# 2. Stop Samba
share-off() {
    sudo systemctl stop smb nmb
    echo -e "\e[31mSamba sharing is now OFF\e[0m"
}

# 3. Add a new Secure Read-Only share
share-add() {
    local target_path=$1
    local share_name=$(basename "$target_path")
    if [[ -z "$target_path" ]]; then
        echo -e "\e[31mError: Please provide a file path.\e[0m"
        return 1
    fi
    sudo bash -c "cat >> /etc/samba/smb.conf <<SHARE_EOF

[$share_name]
   path = $target_path
   valid users = pulina
   public = no
   writable = no
   browsable = yes
   create mask = 0644
   directory mask = 0755
SHARE_EOF"
    sudo systemctl restart smb nmb
    echo -e "\e[32mAdded share [$share_name] for $target_path\e[0m"
}

# 4. Remove a share by name
share-remove() {
    local share_name=$1
    if [[ -z "$share_name" ]]; then
        echo -e "\e[31mError: Please provide the share name.\e[0m"
        return 1
    fi
    # Removes the config block (approx 8 lines)
    sudo sed -i "/\[$share_name\]/,+8d" /etc/samba/smb.conf
    sudo systemctl restart smb nmb
    echo -e "\e[31mRemoved share [$share_name]\e[0m"
}

# 5. Show All Active Shared Folders
share-list() {
    echo -e "\e[1;33mCurrent Samba Shares for user [pulina]:\e[0m"
    # Extract share names, excluding global
    grep -Po '(?<=\[)[^\]]+(?=\])' /etc/samba/smb.conf | grep -v "global" | while read -r share; do
        # Changed 'path' to 'folder_path' to avoid Zsh keyword conflict
        local folder_path=$(grep -A 1 "\[$share\]" /etc/samba/smb.conf | grep "path =" | cut -d'=' -f2 | xargs)
        echo -e "  \e[32m➜\e[0m \e[1m$share\e[0m \e[2m($folder_path)\e[0m"
    done
}

# 6. Show connected devices
share-devices() {
    echo -e "\e[1;33mConnected Devices:\e[0m"
    
    # We use -- to prevent grep from misinterpreting the dashes
    # We move the color formatting to the 'echo' command to keep awk happy
    local connections=$(sudo smbstatus -b | grep -v "Service" | grep -v -- "-------" | awk '{print "User: " $2 " | IP: " $5}')
    
    if [[ -z "$connections" ]]; then
        echo -e "  \e[31mNo active connections.\e[0m"
    else
        # This handles the colors during the final print
        echo "$connections" | while read -r line; do
            echo -e "  \e[32m➜\e[0m $line"
        done
    fi
}

# 7. Change permissions of a share directory
share-perm() {
    local target_path=$1
    local perm=${2:-755}
    if [[ -z "$target_path" ]]; then
        echo -e "\e[31mError: Please provide a directory path.\e[0m"
        return 1
    fi
    sudo chmod -R $perm "$target_path"
    sudo chown -R pulina:pulina "$target_path"
    echo -e "\e[34mPermissions for $target_path updated to $perm\e[0m"
}

# 8. Updated Help Menu
smb-help() {
    echo -e "\e[1;33mCustom Samba Commands:\e[0m"
    echo -e "  \e[32mshare-on\e[0m      : Start services and show all active IPs."
    echo -e "  \e[31mshare-off\e[0m     : Stop all Samba services."
    echo -e "  \e[32mshare-add\e[0m     : [path] Add a new Read-Only share."
    echo -e "  \e[31mshare-remove\e[0m  : [name] Remove a share from config."
    echo -e "  \e[36mshare-list\e[0m    : Show all currently shared folders."
    echo -e "  \e[35mshare-devices\e[0m : Show IPs of connected devices."
    echo -e "  \e[34mshare-perm\e[0m    : [path] [mode] Change folder permissions.    777 full privileges, 755 read/execute, 700 owner only (default: 755)."
    echo -e "  \e[33msmb-help\e[0m      : Show this list of commands."
}

### END SAMBA SHARES SUITE

EOF

echo "Appended Samba functions to $cfg"
echo
echo "To apply them now, run:" 
echo "  source $cfg"
echo "Or open a new terminal session."

exit 0
