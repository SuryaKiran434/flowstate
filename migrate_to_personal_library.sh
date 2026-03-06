#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# migrate_to_personal_library.sh — Interactive Flowstate migration manager
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

print_db_state() {
    echo ""
    echo -e "${CYAN}── Current DB state ──${NC}"
    docker exec flowstate_db psql -U flowstate -c "
    SELECT
        (SELECT COUNT(*) FROM tracks)         AS tracks,
        (SELECT COUNT(*) FROM track_features) AS features,
        (SELECT COUNT(*) FROM user_tracks)    AS user_tracks,
        (SELECT COUNT(*) FROM users)          AS users;
    "
    echo ""
}

print_menu() {
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║       Flowstate Migration Manager            ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${CYAN}1)${NC} Show DB state only (dry run)"
    echo -e "  ${CYAN}2)${NC} Wipe track data only (keeps users + features)"
    echo -e "  ${CYAN}3)${NC} Wipe ALL track data + features (keeps users)"
    echo -e "  ${CYAN}4)${NC} Trigger DAG only (no wipe)"
    echo -e "  ${CYAN}5)${NC} Wipe ALL + trigger fresh DAG  ${RED}[full reset]${NC}"
    echo -e "  ${CYAN}6)${NC} Exit"
    echo ""
}

confirm() {
    local msg="$1"
    echo -e "${YELLOW}⚠  $msg${NC}"
    read -r -p "    Type 'yes' to confirm: " input
    if [ "$input" != "yes" ]; then
        echo "  Aborted."
        exit 0
    fi
}

trigger_dag() {
    echo -e "${CYAN}── Triggering DAG ──${NC}"
    docker exec -u airflow flowstate_airflow airflow dags trigger feature_enrichment
    echo -e "${GREEN}✔ DAG triggered — monitor at http://localhost:8080/dags/feature_enrichment${NC}"
}

wipe_tracks_only() {
    docker exec flowstate_db psql -U flowstate -c "
    TRUNCATE TABLE user_tracks CASCADE;
    TRUNCATE TABLE tracks CASCADE;
    "
    echo -e "${GREEN}✔ Wiped tracks + user_tracks (features preserved)${NC}"
}

wipe_all() {
    docker exec flowstate_db psql -U flowstate -c "
    TRUNCATE TABLE track_features CASCADE;
    TRUNCATE TABLE user_tracks CASCADE;
    TRUNCATE TABLE tracks CASCADE;
    "
    echo -e "${GREEN}✔ Wiped tracks, track_features, user_tracks${NC}"
    echo -e "${GREEN}✔ Users table preserved (login sessions intact)${NC}"
}

print_db_state
print_menu

read -r -p "Select an option [1-6]: " choice

case "$choice" in
    1)
        echo "Nothing changed."
        ;;
    2)
        confirm "This will wipe tracks and user_tracks but keep audio features."
        wipe_tracks_only
        ;;
    3)
        confirm "This will wipe tracks, user_tracks AND all audio features."
        wipe_all
        ;;
    4)
        confirm "This will trigger the DAG without wiping any data."
        trigger_dag
        ;;
    5)
        confirm "This will wipe ALL track data + features and trigger a fresh DAG run."
        wipe_all
        echo ""
        trigger_dag
        ;;
    6)
        echo "Exiting."
        exit 0
        ;;
    *)
        echo -e "${RED}Invalid option. Exiting.${NC}"
        exit 1
        ;;
esac

echo ""
print_db_state