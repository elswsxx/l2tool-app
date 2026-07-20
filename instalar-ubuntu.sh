#!/usr/bin/env bash
#
# Instalador de L2 Toolkit para Ubuntu / Linux.
# Uso:
#   curl -fsSL https://raw.githubusercontent.com/elswsxx/l2tool-app/main/instalar-ubuntu.sh | bash
# o descarga este archivo y ejecútalo:  bash instalar-ubuntu.sh
#
set -e

REPO="https://raw.githubusercontent.com/elswsxx/l2tool-app/main/linux"
APPDIR="$HOME/.local/share/l2toolkit"
BINDIR="$HOME/.local/bin"
DESKTOPDIR="$HOME/.local/share/applications"

echo "=================================================="
echo "   Instalando L2 Toolkit para Ubuntu / Linux"
echo "=================================================="
echo

echo "[1/5] Instalando dependencias del sistema (pedirá tu contraseña sudo)..."
sudo apt-get update -qq
# WebKitGTK: intenta 4.1 (Ubuntu 22.04+); si no, cae a 4.0 (Ubuntu 20.04)
if ! sudo apt-get install -y python3 python3-venv python3-pip python3-gi \
        gir1.2-webkit2-4.1 rclone curl 2>/dev/null; then
  sudo apt-get install -y python3 python3-venv python3-pip python3-gi \
        gir1.2-webkit2-4.0 rclone curl
fi

echo "[2/5] Descargando la aplicación..."
mkdir -p "$APPDIR" "$BINDIR" "$DESKTOPDIR"
curl -fsSL "$REPO/l2_toolkit.py" -o "$APPDIR/l2_toolkit.py"
curl -fsSL "$REPO/ui.html"       -o "$APPDIR/ui.html"
curl -fsSL "$REPO/l2toolkit.png" -o "$APPDIR/l2toolkit.png"

echo "[3/5] Creando entorno de Python (con acceso a WebKitGTK del sistema)..."
python3 -m venv --system-site-packages "$APPDIR/venv"
"$APPDIR/venv/bin/pip" install --quiet --upgrade pip
"$APPDIR/venv/bin/pip" install --quiet pywebview

echo "[4/5] Creando lanzador y acceso en el menú..."
cat > "$BINDIR/l2toolkit" <<EOF
#!/usr/bin/env bash
# Evita ventana en blanco con WebKitGTK reciente en algunas GPUs
export WEBKIT_DISABLE_DMABUF_RENDERER=1
cd "$APPDIR"
exec "$APPDIR/venv/bin/python" "$APPDIR/l2_toolkit.py"
EOF
chmod +x "$BINDIR/l2toolkit"

cat > "$DESKTOPDIR/l2toolkit.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=L2 Toolkit
Comment=Calculadora de EXP y gestor de cuentas para Lineage 2
Exec=$BINDIR/l2toolkit
Icon=$APPDIR/l2toolkit.png
Terminal=false
Categories=Utility;Game;
EOF

echo "[5/5] ¡Listo!"
echo
echo "   Ejecuta:   l2toolkit"
echo "   o búscalo en el menú de aplicaciones como 'L2 Toolkit'."
echo
echo "   (Si el comando 'l2toolkit' no aparece, cierra y reabre la terminal,"
echo "    o ejecuta:  export PATH=\"\$PATH:$BINDIR\")"
echo
echo "   Para sincronizar: abre la app -> Configuración -> Conectar mi Google Drive."
