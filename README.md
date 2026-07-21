# L2 Toolkit — Descargas

Herramientas de escritorio para Lineage 2: calculadora de spots de farmeo,
calculadora de nivel calibrable a tu servidor, calculadora económica de crafteo
y gestor de cuentas. Con respaldo y sincronización a tu Google Drive.

## 🪟 Windows — Instalador (recomendado)

**[⬇ Descargar L2Toolkit-Setup.exe](https://github.com/elswsxx/l2tool-app/raw/main/L2Toolkit-Setup.exe)**

Descárgalo y ejecútalo. Instala todo lo necesario (incluye la sincronización con
Google Drive lista para usar) y crea accesos en el menú de inicio y el escritorio.
No requiere permisos de administrador.

> Si Windows muestra "Windows protegió tu PC" (SmartScreen): **Más información →
> Ejecutar de todas formas**. Es normal en apps sin firma de pago.

## 🐧 Ubuntu / Linux

En una terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/elswsxx/l2tool-app/main/instalar-ubuntu.sh | bash
```

Instala dependencias, la app y un acceso en el menú. Luego ejecuta `l2toolkit`.

## 🔄 Actualizaciones

La app se actualiza sola: al abrir, si hay una versión nueva, avisa y con un clic
se instala y se reabre.

## ☁ Tus datos y respaldo (a prueba de pérdidas)

Se guardan en tu equipo y se respaldan en **3 capas independientes**:
1. **Historial local** con fecha en tu PC (funciona sin internet).
2. **Google Drive** (opcional): Configuración → Conectar mi Google Drive. Usa tu
   propia cuenta con permiso mínimo (la app solo ve sus propios archivos).
3. **Snapshots diarios** en la nube.

La sincronización es de tipo **unión**: la nube nunca pierde datos aunque uses
varias PC con la misma cuenta.
