#!/bin/bash
echo "Installing dependencies..."
pip install -r requirements.txt

echo "Building macOS app..."
python setup.py py2app

echo "Build complete. App is in dist/macVMs.app"