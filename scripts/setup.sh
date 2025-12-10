#!/bin/bash

# Setup script for Automated Trading System
# Unix/Linux/MacOS shell script

echo "========================================"
echo "Automated Trading System - Setup"
echo "========================================"
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version
if [ $? -ne 0 ]; then
    echo "ERROR: Python3 not found. Please install Python 3.9 or higher."
    exit 1
fi

echo ""
echo "Creating virtual environment..."
python3 -m venv venv

echo ""
echo "Activating virtual environment..."
source venv/bin/activate

echo ""
echo "Upgrading pip..."
python -m pip install --upgrade pip

echo ""
echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "Installing development dependencies..."
pip install -r requirements-dev.txt

echo ""
echo "Creating data directories..."
mkdir -p data/logs
mkdir -p data/cache
mkdir -p data/backtest_results

echo ""
echo "Setting up environment file..."
if [ ! -f ".env" ]; then
    cp ".env.example" ".env"
    echo "Created .env file from template"
    echo "IMPORTANT: Edit .env and add your Groww API credentials!"
else
    echo ".env file already exists, skipping..."
fi

echo ""
echo "Testing configuration..."
python -c "from src.trader.core.config import get_config; c = get_config(); print('Config loaded successfully!'); print(f'Trading mode: {c.get(\"trading.mode\")}')"

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your Groww API credentials"
echo "2. Review config/default_config.yaml"
echo "3. Run tests: pytest"
echo "4. Start implementing remaining components"
echo ""
echo "REMEMBER: FORCE_PAPER_MODE=1 must stay enabled until"
echo "you complete 2+ weeks of paper trading and all tests pass!"
echo ""
