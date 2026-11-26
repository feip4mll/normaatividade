$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$dockerExe = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $dockerExe) { $dockerExe = 'C:/Program Files/Docker/Docker/resources/bin/docker.exe' }
& $dockerExe info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Abra o Docker Desktop. Se instalou WSL agora, reinicie o Windows primeiro.' }
& $dockerExe compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Falha ao iniciar. Consulte a mensagem do Docker.' }
Write-Host 'Loja: http://localhost:8000 | RabbitMQ: http://localhost:15672'
Write-Host 'Login RabbitMQ: norma / norma-local-demo'
