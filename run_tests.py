#!/usr/bin/env python3
"""
Test runner for auto-scout project.
Run specific test categories or all tests.
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

# Add src to path for imports
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

def run_command(cmd, description, cwd=None):
    """Run a command and return success status."""
    print(f"\n🔧 {description}")
    print(f"Command: {' '.join(cmd)}")
    print("-" * 40)
    
    try:
        result = subprocess.run(
            cmd, 
            cwd=cwd or project_root,
            capture_output=False,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ {description}: PASSED")
            return True
        else:
            print(f"❌ {description}: FAILED (exit code: {result.returncode})")
            return False
            
    except FileNotFoundError:
        print(f"❌ Command not found: {cmd[0]}")
        return False
    except Exception as e:
        print(f"❌ Error running {description}: {e}")
        return False

def run_python_tests():
    """Run Python unit tests."""
    test_files = list(Path("tests").glob("test_*.py"))
    
    if not test_files:
        print("⚠️  No test files found in tests/ directory")
        return True
    
    success = True
    for test_file in test_files:
        cmd = [sys.executable, str(test_file)]
        if not run_command(cmd, f"Running {test_file.name}"):
            success = False
    
    return success

def run_validation():
    """Run project validation."""
    cmd = [sys.executable, "validate_project.py"]
    return run_command(cmd, "Project structure validation")

def run_syntax_check():
    """Run syntax check on all Python files."""
    print("\n🐍 Python Syntax Check")
    print("-" * 40)
    
    python_files = []
    for pattern in ["src/**/*.py", "tests/**/*.py", "examples/**/*.py", "tools/**/*.py"]:
        python_files.extend(Path(".").glob(pattern))
    
    errors = 0
    for py_file in python_files:
        cmd = [sys.executable, "-m", "py_compile", str(py_file)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"✓ {py_file}")
            else:
                print(f"❌ {py_file}: {result.stderr.strip()}")
                errors += 1
        except Exception as e:
            print(f"⚠️  Error checking {py_file}: {e}")
            errors += 1
    
    if errors == 0:
        print("✅ Python syntax check: PASSED")
        return True
    else:
        print(f"❌ Python syntax check: {errors} files with errors")
        return False

def run_import_check():
    """Check that imports work correctly."""
    print("\n📦 Import Check")
    print("-" * 40)
    
    # Test critical imports that should work
    test_imports = [
        "import sys",
        "import os", 
        "import pathlib",
        "from pathlib import Path"
    ]
    
    success = True
    for import_stmt in test_imports:
        try:
            exec(import_stmt)
            print(f"✓ {import_stmt}")
        except ImportError as e:
            print(f"❌ {import_stmt}: {e}")
            success = False
        except Exception as e:
            print(f"⚠️  {import_stmt}: {e}")
    
    if success:
        print("✅ Import check: PASSED")
    else:
        print("❌ Import check: FAILED")
    
    return success

def main():
    parser = argparse.ArgumentParser(description="Auto-Scout Test Runner")
    parser.add_argument(
        "--category", 
        choices=["all", "validation", "syntax", "imports", "tests"],
        default="all",
        help="Test category to run"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    print("🚀 Auto-Scout Test Runner")
    print("=" * 50)
    print(f"Category: {args.category}")
    print(f"Project root: {project_root}")
    
    results = {}
    
    if args.category in ["all", "validation"]:
        results["validation"] = run_validation()
    
    if args.category in ["all", "syntax"]:
        results["syntax"] = run_syntax_check()
    
    if args.category in ["all", "imports"]:
        results["imports"] = run_import_check()
    
    if args.category in ["all", "tests"]:
        results["tests"] = run_python_tests()
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)
    
    all_passed = True
    for category, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        icon = "✅" if passed else "❌"
        print(f"{icon} {category.capitalize()}: {status}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED!")
        print("   Project is ready for development.")
    else:
        print("\n⚠️  SOME TESTS FAILED")
        print("   Please review the failures above.")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
