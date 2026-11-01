# Run from any working directory. Keep this terminal open while viewing the app.
Push-Location -LiteralPath $PSScriptRoot
try {
    $projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $projectPython)) {
        throw 'Project environment missing. Follow README setup instructions first.'
    }
    & $projectPython -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501
    if ($LASTEXITCODE -ne 0) { throw "Dashboard exited with code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
