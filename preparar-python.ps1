$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ deve estar instalado.' }
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependências.' }
Write-Host 'Ambiente pronto. Veja os quatro comandos de terminais no README.md.'
