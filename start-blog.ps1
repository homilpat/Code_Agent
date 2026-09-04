param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DockerCli = Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'
$LmsCli = Join-Path $env:USERPROFILE '.lmstudio\bin\lms.exe'
$PlannerModelKey = 'qwen/qwen3-8b'
$PlannerModelIdentifier = 'planner-model'
$AnswerModelKey = 'google/gemma-4-e4b'
$AnswerModelIdentifier = 'answer-model'
$LmStudioPort = 1234
$BlogUrl = 'http://localhost:3000'
$ApiUrl = 'http://localhost:8080/api/posts'

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Wait-Until([scriptblock]$Check, [int]$TimeoutSeconds, [string]$Description) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            if (& $Check) {
                return
            }
        } catch {
            # The dependency may still be starting.
        }
        Start-Sleep -Seconds 2
    }
    throw "$Description 준비 시간이 초과되었습니다."
}

try {
    Set-Location -LiteralPath $ProjectDir

    if (-not (Test-Path -LiteralPath $DockerCli)) {
        throw "Docker CLI를 찾을 수 없습니다: $DockerCli"
    }
    if (-not (Test-Path -LiteralPath $LmsCli)) {
        throw "LM Studio CLI를 찾을 수 없습니다: $LmsCli"
    }

    Write-Step 'Docker Desktop 확인'
    $dockerReady = $false
    try {
        & $DockerCli info *> $null
        $dockerReady = ($LASTEXITCODE -eq 0)
    } catch {
        $dockerReady = $false
    }
    if (-not $dockerReady) {
        & $DockerCli desktop start
        Wait-Until -TimeoutSeconds 180 -Description 'Docker Desktop' -Check {
            & $DockerCli info *> $null
            return ($LASTEXITCODE -eq 0)
        }
    }
    Write-Host 'Docker 엔진 준비 완료' -ForegroundColor Green

    Write-Step 'LM Studio API 서버 확인'
    $lmStudioReady = $false
    try {
        $modelsResponse = Invoke-RestMethod -Uri "http://127.0.0.1:$LmStudioPort/v1/models" -TimeoutSec 5
        $lmStudioReady = ($null -ne $modelsResponse.data)
    } catch {
        $lmStudioReady = $false
    }
    if (-not $lmStudioReady) {
        & $LmsCli server start --port $LmStudioPort
    }
    Wait-Until -TimeoutSeconds 60 -Description 'LM Studio API 서버' -Check {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$LmStudioPort/v1/models" -TimeoutSec 5
        return ($null -ne $response.data)
    }
    Write-Host "LM Studio API 서버 준비 완료 (포트 $LmStudioPort)" -ForegroundColor Green

    Write-Step '계층형 LLM 모델 확인'
    $modelsResponse = Invoke-RestMethod -Uri "http://127.0.0.1:$LmStudioPort/v1/models" -TimeoutSec 5
    $legacyModelLoaded = @($modelsResponse.data | Where-Object { $_.id -eq 'local-model' }).Count -gt 0
    if ($legacyModelLoaded) {
        & $LmsCli unload local-model
        $modelsResponse = Invoke-RestMethod -Uri "http://127.0.0.1:$LmStudioPort/v1/models" -TimeoutSec 5
    }

    $plannerLoaded = @($modelsResponse.data | Where-Object { $_.id -eq $PlannerModelIdentifier }).Count -gt 0
    if (-not $plannerLoaded) {
        & $LmsCli load $PlannerModelKey --identifier $PlannerModelIdentifier --context-length 8192 --parallel 1 --gpu max -y
        if ($LASTEXITCODE -ne 0) {
            throw 'Qwen Planner 모델 로드에 실패했습니다.'
        }
    }
    Write-Host "$PlannerModelIdentifier 준비 완료" -ForegroundColor Green

    $modelsResponse = Invoke-RestMethod -Uri "http://127.0.0.1:$LmStudioPort/v1/models" -TimeoutSec 5
    $answerLoaded = @($modelsResponse.data | Where-Object { $_.id -eq $AnswerModelIdentifier }).Count -gt 0
    if (-not $answerLoaded) {
        & $LmsCli load $AnswerModelKey --identifier $AnswerModelIdentifier --context-length 8192 --parallel 1 --gpu max -y
        if ($LASTEXITCODE -ne 0) {
            throw 'Gemma Answer 모델 로드에 실패했습니다.'
        }
    }
    Write-Host "$AnswerModelIdentifier 준비 완료" -ForegroundColor Green

    Write-Step '블로그 전체 서비스 실행'
    & $DockerCli compose up -d
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose 서비스 실행에 실패했습니다.'
    }

    Wait-Until -TimeoutSeconds 120 -Description '백엔드 API' -Check {
        $response = Invoke-WebRequest -Uri $ApiUrl -UseBasicParsing -TimeoutSec 5
        return ($response.StatusCode -eq 200)
    }
    Wait-Until -TimeoutSeconds 120 -Description '블로그 화면' -Check {
        $response = Invoke-WebRequest -Uri $BlogUrl -UseBasicParsing -TimeoutSec 5
        return ($response.StatusCode -eq 200)
    }

    Write-Host "`n모든 서비스가 정상 실행되었습니다." -ForegroundColor Green
    & $DockerCli compose ps

    if (-not $NoBrowser) {
        Start-Process $BlogUrl
    }
} catch {
    Write-Host "`n실행 실패: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '이 창의 오류 내용을 확인한 뒤 다시 시도해주세요.' -ForegroundColor Yellow
    Read-Host 'Enter 키를 누르면 창이 닫힙니다'
    exit 1
}
