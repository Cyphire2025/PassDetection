import os
import re

ROOT = r"C:\Users\nipun\Desktop\PassDetection\backend"

REPLACEMENTS = [
    (r"UploadLinkModel", "ClientGroupModel"),
    (r"upload_links", "client_groups"),
    (r"upload_link", "client_group"),
    (r"UploadLink", "ClientGroup"),
    (r"UPLOAD_LINK", "CLIENT_GROUP"),
]

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    for old, new in REPLACEMENTS:
        # Simple string replace works well here except we need to be careful, but given we are completely renaming the concept:
        new_content = re.sub(old, new, new_content)
        
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")
        
def main():
    for root, dirs, files in os.walk(ROOT):
        # exclude some dirs
        if any(x in root for x in [".venv", "venv", "__pycache__", ".git", "alembic\\versions"]):
            continue
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                process_file(filepath)
                
    # Renaming files and dirs
    for root, dirs, files in os.walk(ROOT, topdown=False):
        for name in dirs:
            if "upload_link" in name:
                old_path = os.path.join(root, name)
                new_path = os.path.join(root, name.replace("upload_link", "client_group"))
                os.rename(old_path, new_path)
                print(f"Renamed dir {old_path} -> {new_path}")
                
        for name in files:
            if "upload_link" in name:
                old_path = os.path.join(root, name)
                new_path = os.path.join(root, name.replace("upload_link", "client_group"))
                os.rename(old_path, new_path)
                print(f"Renamed file {old_path} -> {new_path}")

if __name__ == "__main__":
    main()
