# L2 Toolkit — Descargas

Herramientas de escritorio para Lineage 2: calculadora de spots de farmeo,
calculadora de nivel calibrable a tu servidor, calculadora económica de crafteo
y gestor de cuentas. Con respaldo/sincronización a tu Google Drive.

## 🪟 Windows

**[⬇ Descargar L2 EXP Calculator.exe](https://github.com/elswsxx/l2tool-app/raw/main/L2%20EXP%20Calculator.exe)**

No requiere instalación: descarga el `.exe` y ábrelo. La app avisa e instala sola
las nuevas versiones. Requiere Windows 10/11 (usa Edge WebView2, ya incluido).

## 🐧 Ubuntu / Linux

Abre una terminal y pega esta línea (instala dependencias, la app y un acceso en el menú):

```bash
curl -fsSL https://raw.githubusercontent.com/elswsxx/l2tool-app/main/instalar-ubuntu.sh | bash
```

Luego ejecuta `l2toolkit` o búscala en el menú de aplicaciones como **L2 Toolkit**.
Requiere una distribución con WebKitGTK (Ubuntu 20.04+ y derivadas). El instalador
lo resuelve solo.

## 🔄 Actualizaciones

La app revisa este repositorio al abrir. Si hay una versión más nueva, muestra un
aviso y — con un clic — se actualiza sola (reemplaza el binario en Windows, o los
archivos de la app en Linux) y se reabre.

## ☁ Tus datos

Se guardan en tu equipo:
- Windows: `%APPDATA%\L2EXPCalculator\`
- Linux: `~/.config/L2EXPCalculator/`

Con **Configuración → Conectar mi Google Drive** los respaldas y sincronizas en
**tu** cuenta (permiso mínimo: la app solo ve sus propios archivos). Con **Restaurar
desde la nube** los recuperas en otra PC.
