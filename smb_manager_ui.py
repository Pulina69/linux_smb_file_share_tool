#!/usr/bin/env python3
import getpass
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


SMB_CONF = Path("/etc/samba/smb.conf")
PERM_OPTIONS = ["777", "755", "700"]


class CommandError(RuntimeError):
    pass


def run_command(command, use_privilege=False):
    if isinstance(command, str):
        cmd = ["bash", "-lc", command]
    else:
        cmd = command

    if use_privilege and os.geteuid() != 0:
        if shutil.which("pkexec"):
            cmd = ["pkexec", "bash", "-lc", command if isinstance(command, str) else " ".join(map(shlex.quote, command))]
        elif shutil.which("sudo"):
            cmd = ["sudo", "bash", "-lc", command if isinstance(command, str) else " ".join(map(shlex.quote, command))]
        else:
            raise CommandError("No privilege escalation tool found (pkexec/sudo).")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "Unknown command error"
        raise CommandError(stderr)

    return result.stdout.strip()


def detect_services():
    candidates = [("smb", "nmb"), ("smbd", "nmbd")]
    for a, b in candidates:
        a_unit = subprocess.run(["systemctl", "list-unit-files", f"{a}.service"], capture_output=True, text=True)
        b_unit = subprocess.run(["systemctl", "list-unit-files", f"{b}.service"], capture_output=True, text=True)
        if f"{a}.service" in a_unit.stdout and f"{b}.service" in b_unit.stdout:
            return a, b
    return "smb", "nmb"


def service_active(service_name):
    result = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == "active"


def get_ipv4_addresses():
    result = subprocess.run(["ip", "-4", "-o", "addr", "show", "up", "scope", "global"], capture_output=True, text=True)
    if result.returncode != 0:
        return []

    found = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            iface = parts[1]
            ip_addr = parts[3].split("/")[0]
            found.append((iface, ip_addr))
    return found


def parse_shares():
    shares = []
    if not SMB_CONF.exists():
        return shares

    current = None
    data = {}
    with SMB_CONF.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                if current and current.lower() != "global":
                    shares.append({"name": current, "path": data.get("path", "")})
                current = line[1:-1].strip()
                data = {}
                continue
            if "=" in line and current:
                key, value = line.split("=", 1)
                data[key.strip().lower()] = value.strip()

    if current and current.lower() != "global":
        shares.append({"name": current, "path": data.get("path", "")})
    return shares


def sanitize_share_name(path_text):
    name = Path(path_text).name or "share"
    clean = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return clean


def ensure_smb_conf_exists():
    if not SMB_CONF.exists():
        raise CommandError("/etc/samba/smb.conf not found. Install Samba first.")


def add_share(target_path, user_name):
    ensure_smb_conf_exists()
    if not target_path:
        raise CommandError("Please select a directory.")

    share_name = sanitize_share_name(target_path)
    block = f"""
[{share_name}]
   path = {target_path}
   valid users = {user_name}
   public = no
   writable = no
   browsable = yes
   create mask = 0644
   directory mask = 0755
""".strip("\n")

    escaped = shlex.quote(block)
    cmd = f"printf '\n%s\n' {escaped} >> {shlex.quote(str(SMB_CONF))}"
    run_command(cmd, use_privilege=True)


def remove_share(share_name):
    ensure_smb_conf_exists()
    safe_name = shlex.quote(share_name)
    src = shlex.quote(str(SMB_CONF))
    tmp = shlex.quote(f"/tmp/smb_conf_{os.getpid()}.tmp")

    cmd = (
        f"awk -v section={safe_name} '"
        "$0==\"[\"section\"]\"{skip=1;next} "
        "skip && /^\\[/{skip=0} "
        "!skip{print}' "
        f"{src} > {tmp} && cp {src} {src}.bak && mv {tmp} {src}"
    )
    run_command(cmd, use_privilege=True)


def restart_samba_services():
    s1, s2 = detect_services()
    run_command(["systemctl", "restart", s1, s2], use_privilege=True)


def set_permissions(path_text, mode):
    user_name = getpass.getuser()
    group_name = subprocess.run(["id", "-gn", user_name], capture_output=True, text=True).stdout.strip() or user_name
    quoted_path = shlex.quote(path_text)
    run_command(f"chmod -R {shlex.quote(mode)} {quoted_path}", use_privilege=True)
    run_command(f"chown -R {shlex.quote(user_name)}:{shlex.quote(group_name)} {quoted_path}", use_privilege=True)


def get_mode(path_text):
    try:
        stat_bits = os.stat(path_text).st_mode & 0o777
        return format(stat_bits, "03o")
    except OSError:
        return "N/A"


def get_connected_devices():
    try:
        out = run_command("smbstatus -b", use_privilege=True)
    except CommandError:
        return []

    devices = []
    for line in out.splitlines():
        if not line.strip() or line.startswith("Samba version") or line.startswith("PID"):
            continue
        if line.startswith("-") or line.startswith("Service"):
            continue
        parts = line.split()
        if len(parts) >= 5:
            user = parts[1]
            ip = parts[4]
            devices.append((user, ip))
    return devices


def detect_package_manager():
    managers = [
        ("apt-get", "sudo apt-get update && sudo apt-get install -y samba"),
        ("dnf", "sudo dnf install -y samba"),
        ("yum", "sudo yum install -y samba"),
        ("pacman", "sudo pacman -Sy --noconfirm samba"),
        ("zypper", "sudo zypper --non-interactive install samba"),
        ("apk", "sudo apk add samba"),
    ]
    for binary, install_cmd in managers:
        if shutil.which(binary):
            return binary, install_cmd
    return None, None


def samba_installed():
    return shutil.which("smbd") is not None


class SambaManagerUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Samba Management Suite")
        self.geometry("980x620")
        self.minsize(900, 560)

        self.user_name = getpass.getuser()
        self.service_a, self.service_b = detect_services()

        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure("Title.TLabel", font=("DejaVu Sans", 14, "bold"))
        self.style.configure("TabHeader.TLabel", font=("DejaVu Sans", 12, "bold"))

        wrapper = ttk.Frame(self, padding=14)
        wrapper.pack(fill="both", expand=True)

        if os.geteuid() != 0:
            warning = ttk.Label(
                wrapper,
                text="Tip: some actions require admin auth. You may be prompted by pkexec/sudo.",
                foreground="#8a6d1d",
            )
            warning.pack(fill="x", pady=(0, 8))

        tabs = ttk.Notebook(wrapper)
        tabs.pack(fill="both", expand=True)

        self.status_tab = ttk.Frame(tabs, padding=12)
        self.shares_tab = ttk.Frame(tabs, padding=12)
        self.devices_tab = ttk.Frame(tabs, padding=12)
        self.install_tab = ttk.Frame(tabs, padding=12)

        tabs.add(self.status_tab, text="1. SMB Status")
        tabs.add(self.shares_tab, text="2. Shared Folders")
        tabs.add(self.devices_tab, text="3. Connected Devices")
        tabs.add(self.install_tab, text="4. Install Samba")

        self._build_status_tab()
        self._build_shares_tab()
        self._build_devices_tab()
        self._build_install_tab()

        self.refresh_all()

    def _build_status_tab(self):
        ttk.Label(self.status_tab, text="Samba Service Status", style="Title.TLabel").pack(anchor="w", pady=(0, 8))

        self.status_value = ttk.Label(self.status_tab, text="Unknown", font=("DejaVu Sans", 11))
        self.status_value.pack(anchor="w", pady=(0, 10))

        btns = ttk.Frame(self.status_tab)
        btns.pack(anchor="w", pady=(0, 12))

        self.toggle_btn = ttk.Button(btns, text="Toggle SMB", command=self.toggle_samba)
        self.toggle_btn.pack(side="left")

        ttk.Button(btns, text="Refresh", command=self.refresh_status).pack(side="left", padx=8)

        ttk.Label(self.status_tab, text="Available Local IPv4 Addresses", style="TabHeader.TLabel").pack(anchor="w", pady=(8, 6))

        self.ip_list = tk.Listbox(self.status_tab, height=14)
        self.ip_list.pack(fill="both", expand=True)

    def _build_shares_tab(self):
        ttk.Label(self.shares_tab, text="Shared Folders", style="Title.TLabel").grid(row=0, column=0, sticky="w")

        columns = ("name", "path", "perm")
        self.share_tree = ttk.Treeview(self.shares_tab, columns=columns, show="headings", height=16)
        self.share_tree.heading("name", text="Share Name")
        self.share_tree.heading("path", text="Directory")
        self.share_tree.heading("perm", text="Current Perm")
        self.share_tree.column("name", width=180)
        self.share_tree.column("path", width=560)
        self.share_tree.column("perm", width=120, anchor="center")
        self.share_tree.grid(row=1, column=0, columnspan=4, sticky="nsew", pady=(10, 8))

        self.shares_tab.grid_rowconfigure(1, weight=1)
        self.shares_tab.grid_columnconfigure(0, weight=1)

        ttk.Label(self.shares_tab, text="Permission").grid(row=2, column=0, sticky="w")
        self.perm_var = tk.StringVar(value="755")
        self.perm_box = ttk.Combobox(self.shares_tab, values=PERM_OPTIONS, width=8, textvariable=self.perm_var, state="readonly")
        self.perm_box.grid(row=2, column=1, sticky="w", padx=(8, 0))

        ttk.Button(self.shares_tab, text="Apply To Selected", command=self.change_selected_permission).grid(row=2, column=2, sticky="w", padx=10)
        ttk.Button(self.shares_tab, text="- Remove Selected", command=self.remove_selected_share).grid(row=2, column=3, sticky="e")

        actions = ttk.Frame(self.shares_tab)
        actions.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        actions.grid_columnconfigure(0, weight=1)

        ttk.Button(actions, text="Refresh Shares", command=self.refresh_shares).grid(row=0, column=0, sticky="w")
        ttk.Button(actions, text="+ Add Directory", command=self.add_share_from_dialog).grid(row=0, column=1, sticky="e")

    def _build_devices_tab(self):
        ttk.Label(self.devices_tab, text="Connected SMB Devices", style="Title.TLabel").pack(anchor="w", pady=(0, 8))

        cols = ("user", "ip")
        self.device_tree = ttk.Treeview(self.devices_tab, columns=cols, show="headings", height=18)
        self.device_tree.heading("user", text="User")
        self.device_tree.heading("ip", text="Device IP")
        self.device_tree.column("user", width=260)
        self.device_tree.column("ip", width=480)
        self.device_tree.pack(fill="both", expand=True)

        ttk.Button(self.devices_tab, text="Refresh Devices", command=self.refresh_devices).pack(anchor="e", pady=(8, 0))

    def _build_install_tab(self):
        ttk.Label(self.install_tab, text="Samba Installation", style="Title.TLabel").pack(anchor="w", pady=(0, 8))

        self.install_status = ttk.Label(self.install_tab, text="Checking...", font=("DejaVu Sans", 11))
        self.install_status.pack(anchor="w", pady=(0, 8))

        self.distro_label = ttk.Label(self.install_tab, text="Distro / package manager: detecting...")
        self.distro_label.pack(anchor="w", pady=(0, 14))

        self.install_btn = ttk.Button(self.install_tab, text="Install Samba", command=self.install_samba)
        self.install_btn.pack(anchor="w")

        ttk.Button(self.install_tab, text="Re-check", command=self.refresh_install_status).pack(anchor="w", pady=(8, 0))

    def refresh_all(self):
        self.refresh_status()
        self.refresh_shares()
        self.refresh_devices()
        self.refresh_install_status()

    def refresh_status(self):
        active = service_active(self.service_a) or service_active(self.service_b)
        state_text = "ACTIVE" if active else "INACTIVE"
        self.status_value.config(text=f"Samba status: {state_text} ({self.service_a}/{self.service_b})")
        self.toggle_btn.config(text="Set INACTIVE" if active else "Set ACTIVE")

        self.ip_list.delete(0, tk.END)
        for iface, addr in get_ipv4_addresses():
            self.ip_list.insert(tk.END, f"{iface}: {addr}")
        if self.ip_list.size() == 0:
            self.ip_list.insert(tk.END, "No active IPv4 addresses found")

    def toggle_samba(self):
        active = service_active(self.service_a) or service_active(self.service_b)
        action = "stop" if active else "start"
        try:
            run_command(["systemctl", action, self.service_a, self.service_b], use_privilege=True)
            self.refresh_status()
        except CommandError as exc:
            messagebox.showerror("Samba Action Failed", str(exc))

    def refresh_shares(self):
        self.share_tree.delete(*self.share_tree.get_children())
        for item in parse_shares():
            path_text = item["path"]
            mode = get_mode(path_text) if path_text else "N/A"
            self.share_tree.insert("", "end", values=(item["name"], path_text, mode))

    def selected_share(self):
        selected = self.share_tree.selection()
        if not selected:
            return None
        values = self.share_tree.item(selected[0], "values")
        if not values:
            return None
        return values[0], values[1], values[2]

    def add_share_from_dialog(self):
        directory = filedialog.askdirectory(title="Select directory to share")
        if not directory:
            return
        try:
            add_share(directory, self.user_name)
            restart_samba_services()
            self.refresh_shares()
            messagebox.showinfo("Share Added", f"Added share: {sanitize_share_name(directory)}")
        except CommandError as exc:
            messagebox.showerror("Add Share Failed", str(exc))

    def remove_selected_share(self):
        selected = self.selected_share()
        if not selected:
            messagebox.showwarning("No Selection", "Select a share to remove.")
            return
        share_name = selected[0]
        if not messagebox.askyesno("Confirm Remove", f"Remove share [{share_name}] from smb.conf?"):
            return

        try:
            remove_share(share_name)
            restart_samba_services()
            self.refresh_shares()
        except CommandError as exc:
            messagebox.showerror("Remove Share Failed", str(exc))

    def change_selected_permission(self):
        selected = self.selected_share()
        if not selected:
            messagebox.showwarning("No Selection", "Select a share first.")
            return
        _, path_text, _ = selected
        mode = self.perm_var.get()
        if not path_text or not os.path.isdir(path_text):
            messagebox.showerror("Invalid Path", "Selected share path is not a valid directory.")
            return

        try:
            set_permissions(path_text, mode)
            self.refresh_shares()
        except CommandError as exc:
            messagebox.showerror("Permission Update Failed", str(exc))

    def refresh_devices(self):
        self.device_tree.delete(*self.device_tree.get_children())
        devices = get_connected_devices()
        if not devices:
            self.device_tree.insert("", "end", values=("No active connections", "-"))
            return
        for user, ip in devices:
            self.device_tree.insert("", "end", values=(user, ip))

    def refresh_install_status(self):
        installed = samba_installed()
        self.install_status.config(text="Samba installed: YES" if installed else "Samba installed: NO")

        distro = self.detect_distro_name()
        pkg, _ = detect_package_manager()
        pkg_text = pkg if pkg else "unsupported"
        self.distro_label.config(text=f"Distro: {distro} | Package manager: {pkg_text}")

    def install_samba(self):
        if samba_installed():
            messagebox.showinfo("Samba", "Samba is already installed.")
            self.refresh_install_status()
            return

        pkg, install_cmd = detect_package_manager()
        if not install_cmd:
            messagebox.showerror("Unsupported", "Could not detect supported package manager.")
            return

        if not messagebox.askyesno("Install Samba", f"Install Samba using {pkg}?"):
            return

        try:
            if os.geteuid() == 0:
                cmd = install_cmd.replace("sudo ", "")
            else:
                cmd = install_cmd
            run_command(cmd, use_privilege=False)
            self.refresh_install_status()
            messagebox.showinfo("Install Complete", "Samba installation finished.")
        except CommandError as exc:
            messagebox.showerror("Install Failed", str(exc))

    @staticmethod
    def detect_distro_name():
        release = Path("/etc/os-release")
        if not release.exists():
            return socket.gethostname()
        data = {}
        for raw in release.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            data[key] = value.strip().strip('"')
        return data.get("PRETTY_NAME") or data.get("NAME") or "Unknown Linux"


if __name__ == "__main__":
    app = SambaManagerUI()
    app.mainloop()
