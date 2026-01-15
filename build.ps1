Write-Host ">>> AG Studio Build Script (Windows) Started" -ForegroundColor Cyan

# 1. Install dependencies
Write-Host "Checking/Installing dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt

# 2. Run the build script
Write-Host "Running build.py..." -ForegroundColor Yellow
python build.py

Write-Host ">>> Build Complete! Run 'python app.py' to start the server." -ForegroundColor Green
