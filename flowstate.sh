#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# flowstate.sh — One-command startup for the Flowstate dev environment
#
# Usage:
#   ./flowstate.sh            # Start everything
#   ./flowstate.sh --rebuild  # Force rebuild Docker images (after code changes)
#   ./flowstate.sh --down     # Stop and remove all containers
#   ./flowstate.sh --seed     # Trigger the Airflow feature_enrichment DAG
#   ./flowstate.sh --status   # Show container health and feature store stats
#   ./flowstate.sh --logs     # Tail live logs from all services
#
# Place this file in your flowstate/ root directory.
# Make executable once: chmod +x flowstate.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/flowstate_$(date +%Y%m%d_%H%M%S).log"
COMPOSE="docker-compose"

# Service readiness timeouts (seconds)
TIMEOUT_DB=60
TIMEOUT_BACKEND=90
TIMEOUT_AIRFLOW=180

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"

log() {
    local level="$1"; shift
    local msg="$*"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] [$level] $msg" >> "$LOG_FILE"
    case "$level" in
        INFO)  echo -e "${GREEN}✔${NC}  $msg" ;;
        WARN)  echo -e "${YELLOW}⚠${NC}  $msg" ;;
        ERROR) echo -e "${RED}✖${NC}  $msg" ;;
        STEP)  echo -e "\n${BOLD}${BLUE}▶ $msg${NC}" ;;
        DATA)  echo -e "${CYAN}   $msg${NC}" ;;
    esac
}

die() {
    log ERROR "$1"
    echo -e "\n${RED}Startup failed. Check logs: $LOG_FILE${NC}"
    exit 1
}

# Wait for a container to be healthy, with retry and timeout
wait_healthy() {
    local container="$1"
    local timeout="$2"
    local elapsed=0
    local interval=5

    log INFO "Waiting for $container to be healthy..."
    while [ $elapsed -lt $timeout ]; do
        local status
        status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found")
        case "$status" in
            healthy)
                log INFO "$container is healthy"
                return 0
                ;;
            unhealthy)
                log ERROR "$container is unhealthy"
                docker logs "$container" --tail 20 >> "$LOG_FILE" 2>&1
                return 1
                ;;
            not_found)
                log WARN "$container not found yet, retrying..."
                ;;
        esac
        sleep $interval
        elapsed=$((elapsed + interval))
        echo -ne "   ${YELLOW}waiting... ${elapsed}s / ${timeout}s${NC}\r"
    done
    die "$container did not become healthy within ${timeout}s"
}

# Wait for a URL to respond 200
wait_url() {
    local name="$1"
    local url="$2"
    local timeout="$3"
    local elapsed=0
    local interval=5

    log INFO "Waiting for $name at $url..."
    while [ $elapsed -lt $timeout ]; do
        if curl -sf "$url" -o /dev/null 2>/dev/null; then
            log INFO "$name is responding"
            return 0
        fi
        sleep $interval
        elapsed=$((elapsed + interval))
        echo -ne "   ${YELLOW}waiting... ${elapsed}s / ${timeout}s${NC}\r"
    done
    log WARN "$name did not respond within ${timeout}s — it may still be starting"
    return 0  # non-fatal, just warn
}

# ── Preflight checks ──────────────────────────────────────────────────────────
preflight() {
    log STEP "Running preflight checks"

    # Docker running?
    docker info > /dev/null 2>&1 || die "Docker is not running. Start Docker Desktop first."
    log INFO "Docker is running"

    # docker-compose available?
    docker-compose version > /dev/null 2>&1 || die "docker-compose not found"
    log INFO "docker-compose found"

    # .env file exists?
    if [ ! -f "$SCRIPT_DIR/.env" ]; then
        log WARN ".env not found — copying from .env.example"
        cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
        die ".env created from template. Fill in SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET then re-run."
    fi

    # Spotify credentials set?
    local client_id
    client_id=$(grep -E "^SPOTIFY_CLIENT_ID=" "$SCRIPT_DIR/.env" | cut -d= -f2 | tr -d ' ')
    if [ -z "$client_id" ] || [ "$client_id" = "your_spotify_client_id_here" ]; then
        die "SPOTIFY_CLIENT_ID not set in .env. Add your Spotify app credentials."
    fi
    log INFO "Spotify credentials found"

    # Disk space (warn if < 2GB free) — macOS-compatible
    local free_gb
    free_gb=$(df -g "$SCRIPT_DIR" 2>/dev/null | awk 'NR==2 {print $4}' || echo "99")
    if [ "${free_gb:-0}" -lt 2 ]; then
        log WARN "Low disk space: ${free_gb}GB free. Docker images need ~2GB."
    else
        log INFO "Disk space OK: ${free_gb}GB free"
    fi
}

# ── Start services ────────────────────────────────────────────────────────────
start_services() {
    local rebuild="${1:-}"
    log STEP "Starting Flowstate services"

    cd "$SCRIPT_DIR"

    if [ "$rebuild" = "--rebuild" ]; then
        log INFO "Rebuilding Docker images (this may take a few minutes)..."
        $COMPOSE build --no-cache 2>&1 | tee -a "$LOG_FILE" | grep -E "(Step|Successfully|ERROR|error)" || true
    fi

    log INFO "Starting containers..."
    $COMPOSE up -d 2>&1 | tee -a "$LOG_FILE" | grep -E "(Created|Started|healthy|error)" || true
}

# ── Wait for all services ─────────────────────────────────────────────────────
wait_services() {
    log STEP "Waiting for services to be ready"

    wait_healthy "flowstate_db"      $TIMEOUT_DB
    wait_healthy "flowstate_redis"   30
    wait_url     "Backend API"       "http://localhost:8000/api/v1/health" $TIMEOUT_BACKEND
    wait_url     "Frontend"          "http://localhost:3000"               60
    wait_url     "Airflow"           "http://localhost:8080/health"        $TIMEOUT_AIRFLOW
}

# ── Verify feature store ──────────────────────────────────────────────────────
check_feature_store() {
    log STEP "Checking feature store"

    local result
    result=$(docker exec flowstate_db psql -U flowstate -t -c "
        SELECT
            COUNT(DISTINCT t.id)   AS total_tracks,
            COUNT(tf.track_id)     AS with_features,
            COUNT(ut.track_id)     AS user_tracks
        FROM tracks t
        LEFT JOIN track_features tf ON t.id = tf.track_id
        LEFT JOIN user_tracks ut    ON t.id = ut.track_id;
    " 2>/dev/null | tr -d ' ' || echo "0|0|0")

    local total with_features user_tracks
    total=$(echo "$result"        | awk -F'|' '{print $1}')
    with_features=$(echo "$result" | awk -F'|' '{print $2}')
    user_tracks=$(echo "$result"   | awk -F'|' '{print $3}')

    log DATA "Total tracks:      ${total:-0}"
    log DATA "With features:     ${with_features:-0}"
    log DATA "User tracks:       ${user_tracks:-0}"

    if [ "${with_features:-0}" -eq 0 ]; then
        log WARN "No audio features extracted yet. Run: ./flowstate.sh --seed"
    else
        log INFO "Feature store has ${with_features} tracks with audio features"
    fi
}

# ── Seed pipeline ─────────────────────────────────────────────────────────────
seed_pipeline() {
    log STEP "Triggering feature_enrichment DAG"

    # Check Airflow is ready
    if ! docker exec -u airflow flowstate_airflow airflow version > /dev/null 2>&1; then
        die "Airflow is not ready. Wait a few minutes and try again."
    fi

    # Check a user token exists (required for Spotify API calls in the DAG)
    local user_count
    user_count=$(docker exec flowstate_db psql -U flowstate -t -c "
        SELECT COUNT(*) FROM users WHERE refresh_token IS NOT NULL;
    " 2>/dev/null | tr -d ' \n' || echo "0")

    if [ "${user_count:-0}" -eq 0 ]; then
        log WARN "No authenticated users found."
        log WARN "Log in at http://localhost:3000 first, then run: ./flowstate.sh --seed"
        return 1
    fi

    log INFO "Found $user_count authenticated user(s)"

    # Trigger DAG
    local output
    output=$(docker exec -u airflow flowstate_airflow airflow dags trigger feature_enrichment 2>&1)
    if echo "$output" | grep -q "queued\|running"; then
        log INFO "DAG triggered successfully"
        log DATA "Monitor at: http://localhost:8080/dags/feature_enrichment"
    else
        log WARN "DAG trigger output: $output"
    fi
}

# ── Status ────────────────────────────────────────────────────────────────────
show_status() {
    log STEP "Flowstate status"

    echo ""
    echo -e "${BOLD}Container health:${NC}"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" \
        --filter "name=flowstate" 2>/dev/null || true

    echo ""
    check_feature_store

    echo ""
    echo -e "${BOLD}Last DAG run:${NC}"
    docker exec -u airflow flowstate_airflow airflow dags list-runs \
        -d feature_enrichment --no-backfill 2>/dev/null | tail -5 || true
}

# ── Logs ──────────────────────────────────────────────────────────────────────
tail_logs() {
    log INFO "Tailing logs (Ctrl+C to stop)..."
    $COMPOSE logs -f --tail=50 backend airflow 2>&1
}

# ── Down ──────────────────────────────────────────────────────────────────────
bring_down() {
    log STEP "Stopping Flowstate"
    cd "$SCRIPT_DIR"
    $COMPOSE down
    log INFO "All containers stopped"
}

# ── Print URLs ────────────────────────────────────────────────────────────────
print_urls() {
    echo ""
    echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}${GREEN}  🎵 Flowstate is ready!${NC}"
    echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "  ${CYAN}Frontend${NC}    →  http://localhost:3000"
    echo -e "  ${CYAN}Backend API${NC} →  http://localhost:8000/docs"
    echo -e "  ${CYAN}Airflow${NC}     →  http://localhost:8080  (admin/admin)"
    echo -e "  ${CYAN}MLflow${NC}      →  http://localhost:5001"
    echo ""
    echo -e "  ${YELLOW}Next steps:${NC}"
    echo -e "  1. Log in at http://localhost:3000 with Spotify"
    echo -e "  2. Run ${BOLD}./flowstate.sh --seed${NC} to populate the feature store"
    echo -e "  3. Monitor pipeline at http://localhost:8080"
    echo ""
    echo -e "  ${YELLOW}Logs saved to:${NC} $LOG_FILE"
    echo -e "${BOLD}${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    local arg="${1:-}"

    echo -e "${BOLD}${BLUE}"
    echo "  ███████╗██╗      ██████╗ ██╗    ██╗███████╗████████╗ █████╗ ████████╗███████╗"
    echo "  ██╔════╝██║     ██╔═══██╗██║    ██║██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝██╔════╝"
    echo "  █████╗  ██║     ██║   ██║██║ █╗ ██║███████╗   ██║   ███████║   ██║   █████╗  "
    echo "  ██╔══╝  ██║     ██║   ██║██║███╗██║╚════██║   ██║   ██╔══██║   ██║   ██╔══╝  "
    echo "  ██║     ███████╗╚██████╔╝╚███╔███╔╝███████║   ██║   ██║  ██║   ██║   ███████╗"
    echo "  ╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚══════╝"
    echo -e "${NC}"

    log INFO "Flowstate startup — log: $LOG_FILE"

    case "$arg" in
        --down)
            bring_down
            ;;
        --seed)
            seed_pipeline
            ;;
        --status)
            show_status
            ;;
        --logs)
            tail_logs
            ;;
        --rebuild)
            preflight
            start_services "--rebuild"
            wait_services
            check_feature_store
            print_urls
            ;;
        "")
            preflight
            start_services
            wait_services
            check_feature_store
            print_urls
            ;;
        *)
            echo "Usage: ./flowstate.sh [--rebuild|--down|--seed|--status|--logs]"
            exit 1
            ;;
    esac
}

main "$@"
