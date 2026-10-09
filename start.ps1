# ============================================================
# Quick Start Script for Multimodal Literature Assistant
# Usage: powershell -ExecutionPolicy Bypass -File .\start.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Multimodal Literature Assistant - Start" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step 1: Check .env file
if (-not (Test-Path ".env")) {
    Write-Host "[1/5] .env not found, creating from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "      Please edit .env with your API_KEY and rerun" -ForegroundColor Red
    exit 1
} else {
    Write-Host "[1/5] .env file exists" -ForegroundColor Green
}

# Step 2: Check Docker
Write-Host "[2/5] Checking Docker..."
try {
    docker info | Out-Null
    Write-Host "      Docker is running" -ForegroundColor Green
} catch {
    Write-Host "      Docker is not running, please start Docker Desktop first" -ForegroundColor Red
    exit 1
}

# Step 3: Build images
Write-Host "[3/5] Building Docker images (first time may take 5-15 min)..."
docker-compose build

# Step 4: Start base services first (neo4j + redis)
Write-Host "[4/5] Starting Neo4j and Redis..." -ForegroundColor Yellow
docker-compose up -d neo4j redis

# Step 5: Wait for Neo4j to be healthy (max 180 seconds, first start may be slow)
Write-Host "[5/5] Waiting for Neo4j to be ready (max 180s)..." -ForegroundColor Yellow
$maxWait = 180
$waited = 0
while ($waited -lt $maxWait) {
    $status = docker inspect literature-neo4j --format "{{.State.Health.Status}}" 2>$null
    if ($status -eq "healthy") {
        Write-Host "      Neo4j is ready (waited $waited s)" -ForegroundColor Green
        break
    }
    Start-Sleep -Seconds 5
    $waited += 5
    Write-Host "      waiting... ${waited}s / ${maxWait}s (status: $status)"
}

if ($waited -ge $maxWait) {
    Write-Host "      WARNING: Neo4j not ready in $maxWait s, continuing anyway" -ForegroundColor Red
}

# Start all services
Write-Host "      Starting Backend, Worker, Frontend..." -ForegroundColor Yellow
docker-compose up -d

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Started successfully!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Frontend:  http://localhost:5173"
Write-Host "  API Docs:  http://localhost:8000/docs"
Write-Host "  Neo4j:     http://localhost:7474 (neo4j / literature2024)"
Write-Host ""
Write-Host "  Logs:      docker-compose logs -f"
Write-Host "  Stop:      docker-compose down"
Write-Host "========================================"
