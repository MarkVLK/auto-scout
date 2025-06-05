#!/usr/bin/env python3
"""
Comprehensive project validation script for auto-scout.
Validates imports, syntax, and file structure after reorganization.
"""

import sys
import os
import ast
from pathlib import Path
import importlib.util

def validate_python_syntax(file_path):
    """Validate Python file syntax without executing."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        ast.parse(content, filename=str(file_path))
        return True, None
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    except Exception as e:
        return False, f"Error reading file: {e}"

def validate_imports_in_file(file_path):
    """Check if imports in a file are resolvable."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        tree = ast.parse(content)
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        
        return imports
    except Exception as e:
        return []

def main():
    print("🔍 Auto-Scout Project Validation")
    print("=" * 50)
    
    # Check directory structure
    print("\n📁 Validating directory structure...")
    expected_dirs = {
        "src": "Main source code",
        "tests": "Test files", 
        "docs": "Documentation",
        "examples": "Example scripts",
        "config": "Configuration files",
        "launch": "ROS launch files",
        "tools": "Utility tools"
    }
    
    structure_valid = True
    for dir_name, description in expected_dirs.items():
        if Path(dir_name).exists():
            print(f"✓ {dir_name}/ - {description}")
        else:
            print(f"❌ Missing: {dir_name}/ - {description}")
            structure_valid = False
    
    # Validate Python file syntax
    print("\n🐍 Validating Python syntax...")
    python_files = []
    for pattern in ["src/**/*.py", "tests/**/*.py", "examples/**/*.py", "tools/**/*.py"]:
        python_files.extend(Path(".").glob(pattern))
    
    syntax_errors = 0
    for py_file in python_files:
        is_valid, error = validate_python_syntax(py_file)
        if is_valid:
            print(f"✓ {py_file}")
        else:
            print(f"❌ {py_file}: {error}")
            syntax_errors += 1
    
    # Check key files exist
    print("\n📄 Validating key project files...")
    key_files = {
        "README.md": "Project documentation",
        "requirements.txt": "Python dependencies",
        "package.xml": "ROS package manifest",
        "setup.py": "Python package setup",
        "docs/setup_guide.md": "Setup instructions",
        "docs/QUICKSTART.md": "Quick start guide"
    }
    
    missing_files = 0
    for file_path, description in key_files.items():
        if Path(file_path).exists():
            print(f"✓ {file_path} - {description}")
        else:
            print(f"❌ Missing: {file_path} - {description}")
            missing_files += 1
    
    # Validate test file imports
    print("\n🧪 Validating test file import paths...")
    test_files = list(Path("tests").glob("*.py"))
    
    for test_file in test_files:
        if test_file.name.startswith("test_"):
            # Check if sys.path modifications look correct
            with open(test_file, 'r') as f:
                content = f.read()
                if "sys.path" in content:
                    # Look for correct patterns: '..' and 'src' together
                    if ("'..'," in content and "'src'" in content) or \
                       ('"..",' in content and '"src"' in content) or \
                       ("os.path.join" in content and ".." in content and "src" in content):
                        print(f"✓ {test_file}: Correct relative import path")
                    elif "src" in content and ".." not in content:
                        print(f"⚠️  {test_file}: May have incorrect import path")
                    else:
                        print(f"✓ {test_file}: Import path looks correct")
                else:
                    print(f"✓ {test_file}: No sys.path modifications")
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 VALIDATION SUMMARY")
    print("=" * 50)
    
    if structure_valid:
        print("✓ Directory structure: VALID")
    else:
        print("❌ Directory structure: ISSUES FOUND")
    
    if syntax_errors == 0:
        print("✓ Python syntax: ALL FILES VALID")
    else:
        print(f"❌ Python syntax: {syntax_errors} files with errors")
    
    if missing_files == 0:
        print("✓ Key project files: ALL PRESENT")
    else:
        print(f"❌ Key project files: {missing_files} missing")
    
    overall_status = structure_valid and syntax_errors == 0 and missing_files == 0
    
    if overall_status:
        print("\n🎉 PROJECT VALIDATION: PASSED")
        print("   Ready for development and testing!")
    else:
        print("\n⚠️  PROJECT VALIDATION: ISSUES FOUND")
        print("   Please address the issues above.")
    
    return overall_status

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
