# fix_date_templates_working.py
import os
import re

def fix_template_file(filepath):
    """Fix datetime slicing in template files."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Save original
    original = content
    
    # Pattern 1: {{ var[:10] if var else 'N/A' }}
    pattern1 = r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\[:10\]\s*if\s*\1\s*else\s*[\'"]N/A[\'"]\s*\}\}'
    replacement1 = r'{{ \1|format_date if \1 else "N/A" }}'
    
    # Pattern 2: {{ var[:10] }}
    pattern2 = r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\[:10\]\s*\}\}'
    replacement2 = r'{{ \1|format_date }}'
    
    # Pattern 3: {{ var[:19] if var else 'N/A' }}
    pattern3 = r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\[:19\]\s*if\s*\1\s*else\s*[\'"]N/A[\'"]\s*\}\}'
    replacement3 = r'{{ \1|format_date("%Y-%m-%d %H:%M") if \1 else "N/A" }}'
    
    # Pattern 4: {{ var[:19] }}
    pattern4 = r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\[:19\]\s*\}\}'
    replacement4 = r'{{ \1|format_date("%Y-%m-%d %H:%M") }}'
    
    # Apply replacements
    content = re.sub(pattern1, replacement1, content)
    content = re.sub(pattern2, replacement2, content)
    content = re.sub(pattern3, replacement3, content)
    content = re.sub(pattern4, replacement4, content)
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Show what changed
        print(f"\n✅ Fixed: {filepath}")
        print("Changes:")
        original_lines = original.split('\n')
        new_lines = content.split('\n')
        for i in range(len(original_lines)):
            if original_lines[i] != new_lines[i]:
                print(f"  Line {i+1}:")
                print(f"    Was: {original_lines[i].strip()}")
                print(f"    Now: {new_lines[i].strip()}")
        return True
    return False

def show_template_issues():
    """Show templates with date slicing issues."""
    print("🔍 Scanning for templates with date slicing issues...\n")
    
    templates_found = []
    for root, dirs, files in os.walk('templates'):
        for file in files:
            if file.endswith('.html'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for date slicing patterns
                if re.search(r'\[:\d+\]', content):
                    templates_found.append(filepath)
                    
                    # Show the problematic lines
                    print(f"📋 {filepath}:")
                    lines = content.split('\n')
                    for i, line in enumerate(lines, 1):
                        if re.search(r'\[:\d+\]', line):
                            print(f"  Line {i}: {line.strip()[:80]}{'...' if len(line.strip()) > 80 else ''}")
                    print()
    
    return templates_found

if __name__ == '__main__':
    templates_found = show_template_issues()
    
    if templates_found:
        print(f"\nFound {len(templates_found)} templates with date slicing issues.")
        
        # Fix all templates automatically
        print("\n🛠️  Fixing templates automatically...")
        fixed_count = 0
        for filepath in templates_found:
            if fix_template_file(filepath):
                fixed_count += 1
        
        print(f"\n✅ Fixed {fixed_count} templates!")
        
        print("\n🚀 Restart your Flask app and test!")
    else:
        print("✅ No templates with date slicing issues found!")