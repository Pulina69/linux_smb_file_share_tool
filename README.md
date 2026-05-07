# Samba Management Suite (Linux UI)

Desktop UI to manage Samba shares with 4 tabs:

1. SMB Status: start/stop Samba and list local IPv4 addresses.
2. Shared Folders: list shares, view current permissions, change permissions, remove share, add new shared directory.
3. Connected Devices: see active SMB users/IPs.
4. Install Samba: detect if Samba is installed and install by distro package manager.

## Requirements

- Linux
- Python 3 with Tkinter
- Samba commands (`smbstatus`, `smbd`) if already installed
- `pkexec` or `sudo` for privileged operations

## Run

```bash
python3 smb_manager_ui.py
```

## Notes

- Editing `/etc/samba/smb.conf`, service control, and permission changes require admin auth.
- Service names are auto-detected for common variants: `smb/nmb` and `smbd/nmbd`.
- Share names are generated from directory names and sanitized for Samba section format.
- sometime connected devices not show if it happen just refresh




# smb add to shell if you like to use termian and use smb with simple commands

# add-samba-functions installer

What this does
- Detects the current login shell (bash or zsh).
- Backs up the target shell config file.
- Appends the Samba functions block to the bottom of the shell config.

Usage
1. Make the script executable and run it:

```bash
chmod +x add-samba-functions.sh
./add-samba-functions.sh
```

2. Apply changes to the current session:

```bash
source ~/.bashrc   # or source ~/.zshrc depending on your shell
```

Notes
- The installer supports bash and zsh. If you use fish, add the functions manually.
- A timestamped backup of your config file is created before changes.
- The Samba functions assume a local user named `pulina` (as in your original functions). Adjust as needed.

Files created
- `add-samba-functions.sh` — installer script
