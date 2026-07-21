"""
L2 Toolkit - Calculadora de EXP y gestor de cuentas para Lineage 2.

Multiplataforma (Windows / Linux): la interfaz es HTML/CSS/JS (ui.html)
renderizada con pywebview (Edge WebView2 en Windows, WebKitGTK en Linux).
El backend Python maneja persistencia, respaldo en la nube (rclone) y dialogos.
Los datos viven en %APPDATA%\\L2EXPCalculator (Windows) o
~/.config/L2EXPCalculator (Linux).
"""

import datetime
import json
import os
import shutil
import string
import subprocess
import sys
import threading
import urllib.request
import webbrowser

import webview

APP_TITLE = "L2 EXP Calculator"
APP_VERSION = "1.3.1"

# Deteccion de sistema operativo
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

# CREATE_NO_WINDOW solo aplica en Windows; en el resto debe ser 0.
_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0

# Repo PUBLICO. En Windows se descarga el .exe; en Linux se actualizan los
# archivos fuente (carpeta linux/). version.json es comun a ambos.
RELEASES_RAW = "https://raw.githubusercontent.com/elswsxx/l2tool-app/main"
UPDATE_CHECK_URL = f"{RELEASES_RAW}/version.json"
REPO_URL = "https://github.com/elswsxx/l2tool-app"
EXE_NAME = "L2 EXP Calculator.exe"


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #
def data_dir():
    if IS_WINDOWS and os.environ.get("APPDATA"):
        folder = os.path.join(os.environ["APPDATA"], "L2EXPCalculator")
    elif IS_MAC:
        folder = os.path.join(os.path.expanduser("~"), "Library",
                              "Application Support", "L2EXPCalculator")
    elif IS_LINUX:
        base = os.environ.get("XDG_CONFIG_HOME") or \
            os.path.join(os.path.expanduser("~"), ".config")
        folder = os.path.join(base, "L2EXPCalculator")
    elif getattr(sys, "frozen", False):
        folder = os.path.dirname(sys.executable)
    else:
        folder = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(folder, exist_ok=True)
    return folder


SPOTS_FILE = os.path.join(data_dir(), "l2_spots.json")
ACCOUNTS_FILE = os.path.join(data_dir(), "l2_accounts.json")
SETTINGS_FILE = os.path.join(data_dir(), "l2_settings.json")


def resource_path(name):
    """Ruta a un recurso empaquetado (compatible con PyInstaller onefile)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _save(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        return False
    _backup(path)
    return True


# --------------------------------------------------------------------------- #
# Respaldo automatico en la nube
# Prioridad: rclone -> Google Drive (sube SOLO los 3 JSON, permiso drive.file).
# Respaldo local adicional: carpeta OneDrive/Google Drive Desktop si existe.
# --------------------------------------------------------------------------- #
BACKUP_FOLDER_NAME = "L2Toolkit Backup"
RCLONE_REMOTE = "gdrive"


def _data_is_empty():
    """
    True si no hay NADA guardado (0 spots y 0 cuentas). Se usa para NUNCA
    respaldar un estado vacio sobre la nube: asi una instalacion nueva no
    puede borrar el respaldo bueno de otra PC.
    """
    spots = _load(SPOTS_FILE)
    accounts = _load(ACCOUNTS_FILE)
    n_spots = len(spots) if isinstance(spots, list) else 0
    n_acc = len(accounts) if isinstance(accounts, list) else 0
    return n_spots == 0 and n_acc == 0


def _rclone_exe():
    exe = shutil.which("rclone")
    if exe:
        return exe
    if IS_WINDOWS:
        link = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                            "Microsoft", "WinGet", "Links", "rclone.exe")
        return link if os.path.isfile(link) else None
    return None


_rclone_state = {"checked": False, "ok": False}


def rclone_ready():
    """True si rclone esta instalado y el remoto de Google Drive configurado."""
    if not _rclone_state["checked"]:
        _rclone_state["checked"] = True
        exe = _rclone_exe()
        if exe:
            try:
                out = subprocess.run(
                    [exe, "listremotes"], capture_output=True, text=True,
                    timeout=15, creationflags=_NO_WINDOW,
                )
                _rclone_state["ok"] = f"{RCLONE_REMOTE}:" in (out.stdout or "")
            except (OSError, subprocess.SubprocessError):
                _rclone_state["ok"] = False
    return _rclone_state["ok"]


def _rclone_sync_async():
    """Sube los JSON a Google Drive en segundo plano (no bloquea la app)."""
    if not rclone_ready() or _data_is_empty():
        return  # nunca subir un estado vacio sobre la nube
    exe = _rclone_exe()
    dest = f"{RCLONE_REMOTE}:{BACKUP_FOLDER_NAME}"
    try:
        subprocess.Popen([exe, "copy", data_dir(), dest, "--include", "*.json"],
                         creationflags=_NO_WINDOW)
        # snapshot diario con fecha (red de seguridad ante sobrescrituras)
        day = datetime.date.today().isoformat()
        subprocess.Popen([exe, "copy", data_dir(), f"{dest}/versions/{day}",
                          "--include", "*.json"], creationflags=_NO_WINDOW)
    except OSError:
        pass


def cloud_backup_target():
    """Carpeta local sincronizada por una app de nube, si existe."""
    user = os.path.expanduser("~")
    gdrive = [os.path.join(user, "Google Drive"), os.path.join(user, "My Drive"),
              os.path.join(user, "GoogleDrive")]
    if IS_WINDOWS:
        for letter in string.ascii_uppercase:
            for name in ("My Drive", "Mi unidad"):
                gdrive.append(f"{letter}:\\{name}")
    for c in gdrive:
        if os.path.isdir(c):
            return os.path.join(c, BACKUP_FOLDER_NAME), "Google Drive"
    if IS_WINDOWS:
        onedrive = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
        if onedrive and os.path.isdir(onedrive):
            return os.path.join(onedrive, BACKUP_FOLDER_NAME), "OneDrive"
    return None, None


def _backup(path):
    """Respaldo best-effort: rclone a Google Drive + copia a carpeta de nube local."""
    if _data_is_empty():
        return  # no clonar un estado vacio a la nube
    try:
        dest, _ = cloud_backup_target()
        if dest and os.path.exists(path):
            os.makedirs(dest, exist_ok=True)
            shutil.copy2(path, os.path.join(dest, os.path.basename(path)))
    except OSError:
        pass
    _rclone_sync_async()


def backup_all_now():
    if _data_is_empty():
        return  # no clonar un estado vacio a la nube
    try:
        dest, _ = cloud_backup_target()
        if dest:
            os.makedirs(dest, exist_ok=True)
            for f in (SPOTS_FILE, ACCOUNTS_FILE, SETTINGS_FILE):
                if os.path.exists(f):
                    shutil.copy2(f, os.path.join(dest, os.path.basename(f)))
    except OSError:
        pass
    _rclone_sync_async()


# Constantes de dialogo compatibles con pywebview 4/5/6
try:
    DIALOG_SAVE = webview.FileDialog.SAVE
    DIALOG_OPEN = webview.FileDialog.OPEN
except AttributeError:  # pywebview < 5
    DIALOG_SAVE = webview.SAVE_DIALOG
    DIALOG_OPEN = webview.OPEN_DIALOG


# --------------------------------------------------------------------------- #
# API expuesta a JavaScript
# --------------------------------------------------------------------------- #
class Api:
    def get_data(self):
        settings = _load(SETTINGS_FILE)
        if not isinstance(settings, dict):
            settings = {}
        return {
            "spots": _load(SPOTS_FILE),
            "accounts": _load(ACCOUNTS_FILE),
            "settings": settings,
        }

    def save_spots(self, spots):
        return _save(SPOTS_FILE, spots)

    def save_accounts(self, accounts):
        return _save(ACCOUNTS_FILE, accounts)

    def save_settings(self, settings):
        return _save(SETTINGS_FILE, settings)

    def backup_status(self):
        if rclone_ready():
            return {"dir": f"Google Drive / {BACKUP_FOLDER_NAME}",
                    "kind": "Google Drive", "connected": True}
        dest, kind = cloud_backup_target()
        return {"dir": dest, "kind": kind, "connected": bool(kind)}

    def backup_now(self):
        """Respaldo manual inmediato a la nube."""
        backup_all_now()
        if rclone_ready():
            return {"ok": True, "kind": "Google Drive"}
        dest, kind = cloud_backup_target()
        if kind:
            return {"ok": True, "kind": kind}
        return {"ok": False, "error": "No hay un destino de nube configurado"}

    def restore_from_cloud(self):
        """Trae los datos desde la nube y SOBRESCRIBE los locales (sincronización)."""
        if rclone_ready():
            try:
                subprocess.run(
                    [_rclone_exe(), "copy", f"{RCLONE_REMOTE}:{BACKUP_FOLDER_NAME}",
                     data_dir(), "--include", "*.json"],
                    capture_output=True, timeout=90, creationflags=_NO_WINDOW,
                )
                return {"ok": True, "kind": "Google Drive"}
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": "Tiempo de espera agotado"}
            except (OSError, subprocess.SubprocessError) as e:
                return {"ok": False, "error": str(e)}

        dest, kind = cloud_backup_target()
        if dest and os.path.isdir(dest):
            restored = []
            try:
                for name in ("l2_spots.json", "l2_accounts.json", "l2_settings.json"):
                    src = os.path.join(dest, name)
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(data_dir(), name))
                        restored.append(name)
            except OSError as e:
                return {"ok": False, "error": str(e)}
            if restored:
                return {"ok": True, "kind": kind, "files": restored}
            return {"ok": False, "error": "No se encontró un respaldo en la nube"}
        return {"ok": False, "error": "No hay respaldo en la nube para restaurar"}

    def disconnect_drive(self):
        """Desvincula la cuenta de Google Drive (borra el remoto de rclone)."""
        exe = _rclone_exe()
        if exe:
            try:
                subprocess.run([exe, "config", "delete", RCLONE_REMOTE],
                               capture_output=True, timeout=15, creationflags=_NO_WINDOW)
            except (OSError, subprocess.SubprocessError):
                pass
        _rclone_state["checked"] = False
        return {"ok": True}

    def open_data_folder(self):
        try:
            if IS_WINDOWS:
                os.startfile(data_dir())  # noqa: S606
            elif IS_MAC:
                subprocess.Popen(["open", data_dir()])
            else:
                subprocess.Popen(["xdg-open", data_dir()])
            return True
        except OSError:
            return False

    def connect_drive(self):
        """
        Conecta el Google Drive DEL USUARIO: instala rclone si falta (Windows) y
        abre el navegador para que autorice su cuenta (permiso drive.file).
        """
        exe = _rclone_exe()
        if not exe and IS_WINDOWS:
            try:
                subprocess.run(
                    ["winget", "install", "Rclone.Rclone", "--silent",
                     "--accept-source-agreements", "--accept-package-agreements"],
                    capture_output=True, timeout=300, creationflags=_NO_WINDOW,
                )
            except (OSError, subprocess.SubprocessError):
                pass
            exe = _rclone_exe()
        if not exe:
            hint = ("Instálalo desde rclone.org" if IS_WINDOWS
                    else "En Ubuntu: sudo apt install rclone")
            return {"ok": False, "error": f"rclone no está instalado. {hint}"}
        try:
            subprocess.run(
                [exe, "config", "create", RCLONE_REMOTE, "drive", "scope=drive.file"],
                capture_output=True, timeout=300, creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Tiempo de espera agotado en la autorización"}
        except (OSError, subprocess.SubprocessError):
            return {"ok": False, "error": "No se pudo iniciar la configuración de rclone"}

        _rclone_state["checked"] = False  # re-detectar
        if rclone_ready():
            if _data_is_empty():
                # PC nueva sin datos: TRAE los de la nube (no subas vacio encima)
                r = self.restore_from_cloud()
                return {"ok": True, "pulled": bool(r.get("ok"))}
            backup_all_now()
            return {"ok": True, "pulled": False}
        return {"ok": False, "error": "La autorización no se completó"}

    def check_update(self):
        """Compara la versión local con version.json del repo público."""
        try:
            req = urllib.request.Request(
                UPDATE_CHECK_URL, headers={"User-Agent": "L2Toolkit"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.load(r)
            latest = str(data.get("version", ""))

            def ver(v):
                return tuple(int(x) for x in v.split(".") if x.isdigit())

            if latest and ver(latest) > ver(APP_VERSION):
                return {"update": True, "version": latest,
                        "notes": data.get("notes", "")}
        except Exception:
            pass
        return {"update": False, "version": APP_VERSION}

    def install_update(self):
        """Descarga e instala la nueva versión (exe en Windows, fuente en Linux)."""
        info = self.check_update()
        if not info.get("update"):
            return {"ok": False, "error": "Ya tienes la última versión"}
        if IS_WINDOWS and getattr(sys, "frozen", False):
            return self._install_update_windows()
        if not IS_WINDOWS:
            return self._install_update_source()
        return {"ok": False, "error": "El auto-update solo funciona en el .exe compilado"}

    def _install_update_source(self):
        """Linux/macOS: descarga los archivos fuente nuevos y reinicia la app."""
        appdir = os.path.dirname(os.path.abspath(__file__))
        base = f"{RELEASES_RAW}/linux"
        try:
            for name in ("l2_toolkit.py", "ui.html"):
                req = urllib.request.Request(
                    f"{base}/{name}", headers={"User-Agent": "L2Toolkit"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    content = r.read()
                if len(content) < 100:
                    return {"ok": False, "error": f"Descarga incompleta de {name}"}
                with open(os.path.join(appdir, name), "wb") as f:
                    f.write(content)
        except Exception as e:
            return {"ok": False, "error": f"No se pudo descargar: {e}"}

        script = os.path.join(appdir, "l2_toolkit.py")
        threading.Timer(
            0.6, lambda: os.execv(sys.executable, [sys.executable, script])).start()
        return {"ok": True}

    def _install_update_windows(self):
        cur = sys.executable
        tmpdir = os.environ.get("TEMP", os.path.dirname(cur))
        new_exe = os.path.join(tmpdir, "l2tool_new.exe")
        url = f"{RELEASES_RAW}/{EXE_NAME.replace(' ', '%20')}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "L2Toolkit"})
            with urllib.request.urlopen(req, timeout=120) as r, open(new_exe, "wb") as f:
                shutil.copyfileobj(r, f)
        except Exception as e:
            return {"ok": False, "error": f"No se pudo descargar: {e}"}

        if not os.path.exists(new_exe) or os.path.getsize(new_exe) < 1_000_000:
            return {"ok": False, "error": "La descarga quedó incompleta"}

        bat = os.path.join(tmpdir, "l2tool_update.bat")
        pid = os.getpid()
        script = (
            "@echo off\r\n"
            "chcp 65001 >NUL\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\r\n'
            "if not errorlevel 1 (\r\n"
            "  timeout /t 1 /nobreak >NUL\r\n"
            "  goto wait\r\n"
            ")\r\n"
            f'move /Y "{new_exe}" "{cur}" >NUL\r\n'
            f'start "" "{cur}"\r\n'
            'del "%~f0"\r\n'
        )
        try:
            with open(bat, "w", encoding="utf-8") as f:
                f.write(script)
            subprocess.Popen(["cmd", "/c", bat], creationflags=_NO_WINDOW)
        except OSError as e:
            return {"ok": False, "error": f"No se pudo iniciar la instalación: {e}"}

        # cerrar la app en medio segundo para que el script pueda reemplazar el exe
        threading.Timer(0.6, lambda: os._exit(0)).start()
        return {"ok": True}

    def app_version(self):
        return APP_VERSION

    def export_spots(self):
        win = webview.windows[0]
        result = win.create_file_dialog(
            DIALOG_SAVE,
            save_filename="l2_spots_backup.json",
            file_types=("Archivo JSON (*.json)",),
        )
        if not result:
            return {"ok": False}
        path = result if isinstance(result, str) else result[0]
        ok = _save(path, _load(SPOTS_FILE))
        return {"ok": ok}

    def import_spots(self):
        win = webview.windows[0]
        result = win.create_file_dialog(
            DIALOG_OPEN,
            file_types=("Archivo JSON (*.json)", "Todos los archivos (*.*)"),
        )
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return []


def main():
    backup_all_now()  # respaldo inicial de lo que ya existe
    api = Api()
    webview.create_window(
        f"{APP_TITLE} v{APP_VERSION}",
        resource_path("ui.html"),
        js_api=api,
        width=1180,
        height=760,
        min_size=(980, 620),
        background_color="#0b0d12",
    )
    webview.start()


if __name__ == "__main__":
    main()
