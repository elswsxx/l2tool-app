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
APP_VERSION = "1.4.1"

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


def _local_snapshot(path):
    """
    Historial LOCAL (independiente de la nube): guarda una copia con fecha en
    data_dir/versions/ cada vez que el contenido cambia, y mantiene las 40 mas
    recientes por archivo. Es la ultima red de seguridad, funciona sin internet.
    """
    try:
        vdir = os.path.join(data_dir(), "versions")
        os.makedirs(vdir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        prev = sorted(g for g in os.listdir(vdir) if g.startswith(stem + "."))
        if prev:  # no duplicar si el ultimo snapshot es identico
            last = os.path.join(vdir, prev[-1])
            try:
                with open(last, "rb") as a, open(path, "rb") as b:
                    if a.read() == b.read():
                        return
            except OSError:
                pass
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(path, os.path.join(vdir, f"{stem}.{ts}.json"))
        keep = sorted(g for g in os.listdir(vdir) if g.startswith(stem + "."))
        for old in keep[:-40]:
            try:
                os.remove(os.path.join(vdir, old))
            except OSError:
                pass
    except OSError:
        pass


def _save(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        return False
    _local_snapshot(path)
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
    name = "rclone.exe" if IS_WINDOWS else "rclone"
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    for cand in (os.path.join(here, name),        # junto al exe (lo pone el instalador)
                 resource_path(name),             # empaquetado en el onefile
                 os.path.join(data_dir(), name)):  # descargado por la app
        if os.path.isfile(cand):
            return cand
    exe = shutil.which("rclone")                  # rclone del sistema
    if exe:
        return exe
    if IS_WINDOWS:
        link = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                            "Microsoft", "WinGet", "Links", "rclone.exe")
        if os.path.isfile(link):
            return link
    return None


def _ensure_rclone():
    """Si no hay rclone, lo descarga desde rclone.org a data_dir (fallback)."""
    exe = _rclone_exe()
    if exe or not IS_WINDOWS:
        return exe
    import tempfile
    import zipfile
    url = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
    try:
        tmpzip = os.path.join(tempfile.gettempdir(), "l2_rclone_dl.zip")
        req = urllib.request.Request(url, headers={"User-Agent": "L2Toolkit"})
        with urllib.request.urlopen(req, timeout=180) as r, open(tmpzip, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(tmpzip) as z:
            member = next((m for m in z.namelist() if m.endswith("rclone.exe")), None)
            if not member:
                return None
            with z.open(member) as src, \
                    open(os.path.join(data_dir(), "rclone.exe"), "wb") as dst:
                shutil.copyfileobj(src, dst)
    except Exception:
        return None
    return _rclone_exe()


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


# --------------------------------------------------------------------------- #
# Sincronizacion tipo UNION: la nube NUNCA pierde datos.
# Cada respaldo sube la union de (local + nube). Una PC con menos datos ya no
# puede borrar lo de otra. No modifica lo local (respeta lo que borraste aqui);
# para traer lo que falte de la nube se usa "Combinar" en la interfaz.
# --------------------------------------------------------------------------- #
# Claves por contenido (para migrar datos viejos sin id). Deben producir el
# MISMO string que las de JS (KEY_SPOT/KEY_ACC/KEY_REC), por eso None -> "".
def _join(*vals):
    return "|".join("" if v is None else str(v) for v in vals)


def _k_spot(s):
    return _join("spot", s.get("spot"), s.get("party"), s.get("minutes"),
                 s.get("exp"), s.get("adena"))


def _k_acc(a):
    return _join("acc", a.get("alias"), a.get("user"), a.get("password"))


def _k_rec(r):
    return _join("rec", r.get("name"))


def _merge_items(local, cloud, keyfn):
    """
    Fusiona por id (o clave de contenido si es dato viejo sin id); para la misma
    clave gana la version con _m mas reciente. Asi se propagan ediciones y
    ARCHIVADOS sin perder nada: nada se borra de verdad, solo se marca archived.
    """
    by_id = {}
    for item in (list(cloud) if isinstance(cloud, list) else []) + \
                (list(local) if isinstance(local, list) else []):
        if not isinstance(item, dict):
            continue
        iid = item.get("id") or keyfn(item)
        cur = by_id.get(iid)
        if cur is None or item.get("_m", 0) >= cur.get("_m", 0):
            by_id[iid] = item
    return list(by_id.values())


def _merge_settings(local, cloud):
    local = local if isinstance(local, dict) else {}
    cloud = cloud if isinstance(cloud, dict) else {}
    merged = dict(cloud)
    merged.update(local)  # escalares (nivel, %, etc.): gana lo local
    ov = dict(cloud.get("lvlOverrides", {}))
    ov.update(local.get("lvlOverrides", {}))
    merged["lvlOverrides"] = ov
    merged["recipes"] = _merge_items(local.get("recipes", []),
                                     cloud.get("recipes", []), _k_rec)
    return merged


def _read_json_dir(folder, name, default):
    try:
        with open(os.path.join(folder, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


_sync_lock = threading.Lock()
_sync_pending = threading.Event()


def _sync_to_cloud():
    """Sube a la nube la UNION de lo local con lo que ya hay en la nube."""
    if _data_is_empty():
        return
    import tempfile
    base = os.path.join(tempfile.gettempdir(), "l2tool_sync")
    pull = os.path.join(base, "pull")
    push = os.path.join(base, "push")
    os.makedirs(push, exist_ok=True)

    local_spots = _load(SPOTS_FILE)
    local_acc = _load(ACCOUNTS_FILE)
    local_set = _load(SETTINGS_FILE)

    exe = _rclone_exe()
    dest = f"{RCLONE_REMOTE}:{BACKUP_FOLDER_NAME}"
    cloud_spots, cloud_acc, cloud_set = [], [], {}
    have_rclone = rclone_ready()
    if have_rclone:
        try:
            os.makedirs(pull, exist_ok=True)
            subprocess.run([exe, "copy", dest, pull, "--include", "*.json"],
                           capture_output=True, timeout=60, creationflags=_NO_WINDOW)
            cloud_spots = _read_json_dir(pull, "l2_spots.json", [])
            cloud_acc = _read_json_dir(pull, "l2_accounts.json", [])
            cloud_set = _read_json_dir(pull, "l2_settings.json", {})
        except (OSError, subprocess.SubprocessError):
            pass

    od, _ = cloud_backup_target()
    if od and os.path.isdir(od):  # unir tambien lo de la carpeta de nube local
        cloud_spots = _merge_items(cloud_spots, _read_json_dir(od, "l2_spots.json", []), _k_spot)
        cloud_acc = _merge_items(cloud_acc, _read_json_dir(od, "l2_accounts.json", []), _k_acc)
        cloud_set = _merge_settings(cloud_set, _read_json_dir(od, "l2_settings.json", {}))

    merged = {
        "l2_spots.json": _merge_items(local_spots, cloud_spots, _k_spot),
        "l2_accounts.json": _merge_items(local_acc, cloud_acc, _k_acc),
        "l2_settings.json": _merge_settings(local_set, cloud_set),
    }
    for name, data in merged.items():
        try:
            with open(os.path.join(push, name), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            return

    if have_rclone:
        try:
            subprocess.run([exe, "copy", push, dest, "--include", "*.json"],
                           capture_output=True, timeout=60, creationflags=_NO_WINDOW)
            day = datetime.date.today().isoformat()
            subprocess.Popen([exe, "copy", push, f"{dest}/versions/{day}",
                              "--include", "*.json"], creationflags=_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass
    if od:
        try:
            os.makedirs(od, exist_ok=True)
            for name in merged:
                shutil.copy2(os.path.join(push, name), os.path.join(od, name))
        except OSError:
            pass


def _sync_worker():
    if not _sync_lock.acquire(blocking=False):
        return  # ya hay una sync corriendo; procesara lo pendiente
    try:
        while _sync_pending.is_set():
            _sync_pending.clear()
            _sync_to_cloud()
    finally:
        _sync_lock.release()


def _trigger_sync():
    if _data_is_empty():
        return
    _sync_pending.set()
    threading.Thread(target=_sync_worker, daemon=True).start()


def _backup(path):
    _trigger_sync()


def backup_all_now():
    _trigger_sync()


# Constantes de dialogo compatibles con pywebview 4/5/6
try:
    DIALOG_SAVE = webview.FileDialog.SAVE
    DIALOG_OPEN = webview.FileDialog.OPEN
except AttributeError:  # pywebview < 5
    DIALOG_SAVE = webview.SAVE_DIALOG
    DIALOG_OPEN = webview.OPEN_DIALOG


_SUCCESS_HTML = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<title>L2 Toolkit · Conectado</title><style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif}
body{min-height:100vh;display:grid;place-items:center;
 background:radial-gradient(1200px 600px at 50% -10%,#1f3a5f 0%,#0b0d12 60%);color:#e7eaf0}
.card{text-align:center;padding:48px 44px;background:rgba(20,24,36,.7);
 border:1px solid #2a3040;border-radius:22px;box-shadow:0 24px 70px rgba(0,0,0,.5);
 backdrop-filter:blur(6px);max-width:440px;animation:pop .45s cubic-bezier(.2,.9,.3,1.2)}
@keyframes pop{from{opacity:0;transform:translateY(14px) scale(.96)}to{opacity:1;transform:none}}
.badge{width:84px;height:84px;margin:0 auto 22px;border-radius:24px;display:grid;place-items:center;
 background:linear-gradient(135deg,#1f3a5f,#356ea5);box-shadow:0 10px 30px rgba(31,58,95,.6);
 font-weight:800;font-size:30px;color:#fff}
.check{width:70px;height:70px;margin:0 auto 20px;border-radius:50%;display:grid;place-items:center;
 background:linear-gradient(135deg,#16a34a,#22c55e);box-shadow:0 10px 30px rgba(34,197,94,.45)}
.check svg{width:38px;height:38px;stroke:#fff;stroke-width:3;fill:none;
 stroke-dasharray:48;stroke-dashoffset:48;animation:draw .5s .25s forwards ease}
@keyframes draw{to{stroke-dashoffset:0}}
h1{font-size:23px;font-weight:800;margin-bottom:10px}
p{color:#9aa4b2;font-size:14.5px;line-height:1.6}
.hint{margin-top:26px;font-size:12.5px;color:#5b8fc7;font-weight:600}
</style></head><body><div class="card">
<div class="badge">L2</div>
<div class="check"><svg viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M20 6L9 17l-5-5"/></svg></div>
<h1>¡Google Drive conectado!</h1>
<p>Tu cuenta quedó vinculada a <b>L2 Toolkit</b>. Tus datos se respaldan y
sincronizan solos en tu Drive, de forma privada.</p>
<div class="hint">Ya puedes cerrar esta pestaña y volver a la app.</div>
</div></body></html>"""


def _auth_template_path():
    """
    Escribe la pagina branded como template para el servidor de auth de rclone
    (rclone authorize --template). Asi la pagina que el usuario ve tras aceptar
    en Google es la NUESTRA, no la gris de rclone. HTML estatico = template Go
    valido sin variables.
    """
    import tempfile
    p = os.path.join(tempfile.gettempdir(), "l2tool_auth_page.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(_SUCCESS_HTML)
    return p


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

    def fetch_cloud_data(self):
        """
        Trae los datos de la nube a una carpeta temporal y los DEVUELVE sin
        tocar lo local (para poder combinarlos desde la interfaz).
        """
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), "l2tool_cloud_fetch")
        os.makedirs(tmp, exist_ok=True)
        got = False
        if rclone_ready():
            try:
                subprocess.run(
                    [_rclone_exe(), "copy", f"{RCLONE_REMOTE}:{BACKUP_FOLDER_NAME}",
                     tmp, "--include", "*.json"],
                    capture_output=True, timeout=90, creationflags=_NO_WINDOW,
                )
                got = True
            except (OSError, subprocess.SubprocessError) as e:
                return {"ok": False, "error": str(e)}
        else:
            dest, _ = cloud_backup_target()
            if dest and os.path.isdir(dest):
                for name in ("l2_spots.json", "l2_accounts.json", "l2_settings.json"):
                    src = os.path.join(dest, name)
                    if os.path.exists(src):
                        try:
                            shutil.copy2(src, os.path.join(tmp, name))
                        except OSError:
                            pass
                got = True
        if not got:
            return {"ok": False, "error": "No hay respaldo en la nube"}
        settings = _load(os.path.join(tmp, "l2_settings.json"))
        return {
            "ok": True,
            "spots": _load(os.path.join(tmp, "l2_spots.json")),
            "accounts": _load(os.path.join(tmp, "l2_accounts.json")),
            "settings": settings if isinstance(settings, dict) else {},
        }

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
        Conecta el Google Drive DEL USUARIO. rclone ya viene con la app (lo pone
        el instalador); si faltara, se descarga solo. Abre el navegador para que
        el usuario autorice su cuenta (permiso mínimo drive.file).
        """
        exe = _ensure_rclone()
        if not exe:
            hint = ("No se pudo obtener rclone automáticamente." if IS_WINDOWS
                    else "En Ubuntu: sudo apt install rclone")
            return {"ok": False, "error": hint}

        # Paso 1: autorizar con NUESTRA pagina como respuesta del login
        # (rclone authorize --template). El usuario ve una sola pagina, la bonita.
        import base64
        blob = base64.b64encode(
            json.dumps({"scope": "drive.file"}).encode()).decode().rstrip("=")
        try:
            out = subprocess.run(
                [exe, "authorize", "drive", blob, "--template", _auth_template_path()],
                capture_output=True, text=True, timeout=300, creationflags=_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Tiempo de espera agotado en la autorización"}
        except (OSError, subprocess.SubprocessError):
            return {"ok": False, "error": "No se pudo iniciar la autorización"}

        # el token JSON viene en stdout entre los marcadores de rclone
        import re
        m = re.search(r"--->\s*(\{.*?\})\s*<---", out.stdout or "", re.S)
        if not m:
            m = re.search(r"(\{\"access_token\".*?\})", out.stdout or "", re.S)
        if not m:
            return {"ok": False, "error": "La autorización no se completó"}
        token = m.group(1).strip()

        # Paso 2: crear el remoto con el token ya en mano (sin abrir nada mas)
        try:
            subprocess.run(
                [exe, "config", "create", RCLONE_REMOTE, "drive",
                 "scope=drive.file", f"token={token}", "--non-interactive"],
                capture_output=True, timeout=60, creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return {"ok": False, "error": "No se pudo guardar la configuración"}

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
        """
        Descarga el INSTALADOR y lo corre en silencio (reemplaza todo limpiamente,
        sin el frágil intercambio del exe onefile que causaba el error de DLL).
        Luego reabre la app.
        """
        cur = sys.executable
        tmpdir = os.environ.get("TEMP", os.path.dirname(cur))
        setup = os.path.join(tmpdir, "l2tool_setup.exe")
        url = f"{RELEASES_RAW}/L2Toolkit-Setup.exe"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "L2Toolkit"})
            with urllib.request.urlopen(req, timeout=180) as r, open(setup, "wb") as f:
                shutil.copyfileobj(r, f)
        except Exception as e:
            return {"ok": False, "error": f"No se pudo descargar: {e}"}

        if not os.path.exists(setup) or os.path.getsize(setup) < 1_000_000:
            return {"ok": False, "error": "La descarga quedó incompleta"}

        bat = os.path.join(tmpdir, "l2tool_update.bat")
        pid = os.getpid()
        script = (
            "@echo off\r\n"
            ":wait\r\n"
            f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\r\n'
            "if not errorlevel 1 (\r\n"
            "  timeout /t 1 /nobreak >NUL\r\n"
            "  goto wait\r\n"
            ")\r\n"
            f'"{setup}" /VERYSILENT /NORESTART /SUPPRESSMSGBOXES\r\n'
            f'start "" "{cur}"\r\n'
            'del "%~f0"\r\n'
        )
        try:
            with open(bat, "w", encoding="utf-8") as f:
                f.write(script)
            subprocess.Popen(["cmd", "/c", bat], creationflags=_NO_WINDOW)
        except OSError as e:
            return {"ok": False, "error": f"No se pudo iniciar la instalación: {e}"}

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
