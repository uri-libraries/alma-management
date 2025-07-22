# Alma Patron Checker - Desktop Application

## Quick Start for Non-Technical Users

### Option 1: Download the Executable (Recommended)
1. Download `AlmaPatronChecker.exe` (Windows) or `AlmaPatronChecker` (Mac/Linux)
2. Double-click to run - no installation needed!
3. Use the search options to find patron information

### Option 2: Run from Source (for developers)
1. Install Python 3.8 or newer
2. Install dependencies: `pip install -r requirements_gui.txt`
3. Run: `python patron_checker_gui.py`

## Creating an Executable

To create a standalone executable that doesn't require Python:

### Install PyInstaller
```bash
pip install -r requirements_gui.txt
```

### Create Executable
```bash
pyinstaller patron_checker_gui.spec
```

This will create:
- `dist/AlmaPatronChecker.exe` (Windows)
- `dist/AlmaPatronChecker` (Mac/Linux)

### Distribution
The executable in the `dist/` folder can be copied to any computer and run without installing Python or any dependencies.

## Features

✅ **Simple Interface** - Radio buttons for search type selection  
✅ **Three Search Methods** - Barcode, Name (First/Last), Email  
✅ **Complete Patron Info** - Loans, fines, blocks, contact info  
✅ **Progress Indicator** - Shows when searching  
✅ **Error Handling** - Clear error messages  
✅ **Formatted Results** - Easy-to-read output  
✅ **No Installation** - Runs as standalone executable  

## Requirements

- `.env` file with API credentials must be in the same folder as the executable
- Internet connection for API calls

## Troubleshooting

**"This app can't run on your PC" (Windows)**: This happens when you build the executable in WSL/Linux but try to run it on Windows. You need to build the executable directly on Windows:
1. Install Python on Windows (not WSL)
2. Open Command Prompt or PowerShell on Windows
3. Navigate to your project folder
4. Run: `pip install -r requirements_gui.txt`
5. Run: `pyinstaller patron_checker_gui.spec`
6. The Windows executable will be in `dist/AlmaPatronChecker.exe`

**"Configuration Error" message**: Make sure the `.env` file is in the same folder as the executable and contains:
```
ALMA_API_KEY=your_api_key_here
ALMA_API_BASE_URL=https://api-na.hosted.exlibrisgroup.com
```

**"API Error" messages**: Check internet connection and API credentials

**Search returns no results**: Verify the patron exists and try different search methods

**Building for Different Operating Systems**:
- **Windows**: Build on Windows or Windows machine
- **Mac**: Build on Mac/macOS machine  
- **Linux**: Build on Linux machine or WSL
- Each OS creates executables that only work on that same OS
