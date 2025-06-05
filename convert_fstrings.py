#!/usr/bin/env python3
"""
Convert f-strings to Python 3.5 compatible format strings
"""

import re
import os
from pathlib import Path

def convert_fstring_to_format(content):
    """Convert f-strings to .format() strings for Python 3.5 compatibility"""
    
    # Pattern to match f-strings: f"text {variable} more text"
    # This is a simplified pattern - complex f-strings may need manual conversion
    fstring_pattern = r'f"([^"]*?{[^}]+}[^"]*?)"'
    
    def replace_fstring(match):
        fstring_content = match.group(1)
        
        # Extract variables from {variable} patterns
        var_pattern = r'{([^}]+)}'
        variables = re.findall(var_pattern, fstring_content)
        
        # Replace {variable} with {0}, {1}, etc.
        format_string = fstring_content
        for i, var in enumerate(variables):
            format_string = format_string.replace(f'{{{var}}}', f'{{{i}}}')
        
        # Create the .format() call
        if variables:
            format_call = f'"{format_string}".format({", ".join(variables)})'
        else:
            format_call = f'"{format_string}"'
        
        return format_call
    
    # Replace all f-strings
    converted_content = re.sub(fstring_pattern, replace_fstring, content)
    
    # Handle single-quoted f-strings too
    fstring_pattern_single = r"f'([^']*?{[^}]+}[^']*?)'"
    
    def replace_fstring_single(match):
        fstring_content = match.group(1)
        
        # Extract variables from {variable} patterns
        var_pattern = r'{([^}]+)}'
        variables = re.findall(var_pattern, fstring_content)
        
        # Replace {variable} with {0}, {1}, etc.
        format_string = fstring_content
        for i, var in enumerate(variables):
            format_string = format_string.replace(f'{{{var}}}', f'{{{i}}}')
        
        # Create the .format() call
        if variables:
            format_call = f"'{format_string}'.format({', '.join(variables)})"
        else:
            format_call = f"'{format_string}'"
        
        return format_call
    
    converted_content = re.sub(fstring_pattern_single, replace_fstring_single, converted_content)
    
    return converted_content

def convert_file(file_path):
    """Convert f-strings in a single file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if file contains f-strings
        if 'f"' not in content and "f'" not in content:
            return False
        
        converted_content = convert_fstring_to_format(content)
        
        # Only write if content changed
        if converted_content != content:
            print(f"Converting f-strings in: {file_path}")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(converted_content)
            return True
        
        return False
        
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

def main():
    """Convert all Python files in src/ directory"""
    print("🔧 Converting f-strings to Python 3.5 compatible format")
    print("=" * 55)
    
    src_dir = Path("src")
    if not src_dir.exists():
        print("❌ src/ directory not found")
        return 1
    
    python_files = list(src_dir.glob("**/*.py"))
    converted_files = 0
    
    for py_file in python_files:
        if convert_file(py_file):
            converted_files += 1
    
    print(f"\n✅ Converted {converted_files} files")
    print("🎉 Python 3.5 compatibility conversion complete!")
    
    return 0

if __name__ == "__main__":
    exit(main())
