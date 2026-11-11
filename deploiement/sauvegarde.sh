#!/usr/bin/env bash
# Sauvegarde quotidienne (X-5) : base SQLite, agent/ (mémoire, paramètres, documents, pièces jointes)
# et sessions du CLI. Les recettes sont déjà couvertes par Git et Drive.
#   0 3 * * * /chemin/deploiement/sauvegarde.sh /mnt/nas/aide-culinaire
set -euo pipefail

RACINE="${AC_RACINE:-/srv/aide-culinaire}"
CIBLE="${1:?Usage : sauvegarde.sh <dossier de destination>}"
CONSERVER="${CONSERVER:-30}"
DATE="$(date +%Y%m%d-%H%M%S)"
TRAVAIL="$(mktemp -d)"
trap 'rm -rf "$TRAVAIL"' EXIT

mkdir -p "$CIBLE"
# Copie cohérente de la base, même pendant une écriture.
sqlite3 "$RACINE/data/app.db" ".backup '$TRAVAIL/app.db'"
# Sessions du moteur API, s'il a servi.
SESSIONS_API=()
[ -d "$RACINE/data/sessions_api" ] && SESSIONS_API=(data/sessions_api)
tar -czf "$CIBLE/aide-culinaire-$DATE.tar.gz" \
    -C "$TRAVAIL" app.db \
    -C "$RACINE" --exclude='agent/.git' agent claude "${SESSIONS_API[@]}"
# Rotation : on garde les $CONSERVER plus récentes.
ls -1t "$CIBLE"/aide-culinaire-*.tar.gz | tail -n +"$((CONSERVER + 1))" | xargs -r rm --
echo "Sauvegarde écrite : $CIBLE/aide-culinaire-$DATE.tar.gz"
