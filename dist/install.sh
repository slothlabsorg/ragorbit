#!/bin/sh
# RAGorbit installer — descarga el zipapp del último release y lo deja en el PATH.
#
#   curl -fsSL https://slothlabs.org/install/ragorbit | sh
#
# Instala un solo archivo (`ragorbit.pyz`) más un lanzador `ragorbit`. No usa pip,
# no crea un venv y no toca tus paquetes de Python: el engine es stdlib pura, así
# que basta un Python 3.10+ ya instalado.
#
# Variables:
#   RAGORBIT_VERSION  tag a instalar (por defecto: latest)
#   RAGORBIT_BIN      dónde poner el lanzador (por defecto: ~/.local/bin)
set -eu

REPO="slothlabsorg/ragorbit"
VERSION="${RAGORBIT_VERSION:-latest}"
BIN_DIR="${RAGORBIT_BIN:-$HOME/.local/bin}"
LIB_DIR="$HOME/.local/share/ragorbit"

info()  { printf '  %s\n' "$1"; }
die()   { printf '\n✗ %s\n' "$1" >&2; exit 1; }

printf '\n🛰️  RAGorbit installer\n\n'

# --- Python 3.10+ ---
PY=""
for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PY="$candidate"
      break
    fi
  fi
done
[ -n "$PY" ] || die "Hace falta Python 3.10 o superior. Instálalo y vuelve a correr esto."
info "Python: $("$PY" --version 2>&1) ($(command -v "$PY"))"

# --- descargador ---
if command -v curl >/dev/null 2>&1; then
  FETCH="curl -fsSL -o"
elif command -v wget >/dev/null 2>&1; then
  FETCH="wget -qO"
else
  die "Hace falta curl o wget."
fi

if [ "$VERSION" = "latest" ]; then
  URL="https://github.com/$REPO/releases/latest/download/ragorbit.pyz"
else
  URL="https://github.com/$REPO/releases/download/$VERSION/ragorbit.pyz"
fi

mkdir -p "$LIB_DIR" "$BIN_DIR"
# Braces are required here: `$VERSION…` makes some shells read the ellipsis's
# UTF-8 bytes as part of the variable name, which under `set -u` aborts the
# install with "unbound variable".
info "Descargando ${VERSION}…"
$FETCH "$LIB_DIR/ragorbit.pyz.tmp" "$URL" || die "No se pudo descargar $URL"

# Comprueba que lo descargado funciona ANTES de reemplazar lo que ya había: si el
# release está a medias, te quedas con la versión que ya tenías.
if ! "$PY" "$LIB_DIR/ragorbit.pyz.tmp" list-nodes >/dev/null 2>&1; then
  rm -f "$LIB_DIR/ragorbit.pyz.tmp"
  die "El archivo descargado no corre. Nada se ha cambiado."
fi
mv "$LIB_DIR/ragorbit.pyz.tmp" "$LIB_DIR/ragorbit.pyz"
chmod 0755 "$LIB_DIR/ragorbit.pyz"

cat > "$BIN_DIR/ragorbit" <<EOF
#!/bin/sh
exec "$PY" "$LIB_DIR/ragorbit.pyz" "\$@"
EOF
chmod 0755 "$BIN_DIR/ragorbit"

NODES=$("$PY" "$LIB_DIR/ragorbit.pyz" list-nodes 2>/dev/null | grep '^Total:' || echo '')
printf '\n✅ Instalado en %s/ragorbit\n' "$BIN_DIR"
[ -n "$NODES" ] && info "$NODES"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    printf '\n⚠️  %s no está en tu PATH. Añádelo:\n' "$BIN_DIR"
    printf '    export PATH="%s:$PATH"\n' "$BIN_DIR"
    ;;
esac

cat <<'EOF'

Para empezar:
    ragorbit list-nodes                 # el catálogo de bloques
    ragorbit --help

Docs:   https://slothlabs.org/ragorbit/docs
Curso:  https://slothlabs.org/rag-course
EOF
