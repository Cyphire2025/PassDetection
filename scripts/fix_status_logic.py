import os
import re

ROOT = r"C:\Users\nipun\Desktop\PassDetection\backend"

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    # Replace ClientGroupStatus with GroupStatus
    new_content = new_content.replace("ClientGroupStatus", "GroupStatus")
    new_content = new_content.replace("UploadLinkExpiredError", "ClientGroupExpiredError")
    new_content = new_content.replace("UploadLinkUsedError", "ClientGroupClosedError")
    
    # Replace logic checking for USED or REVOKED to CLOSED
    new_content = new_content.replace("GroupStatus.USED", "GroupStatus.CLOSED")
    new_content = new_content.replace("GroupStatus.REVOKED", "GroupStatus.CLOSED")
    
    # Fix exception names
    new_content = new_content.replace("ClientGroupExpiredError", "GroupClosedError")
    new_content = new_content.replace("ClientGroupClosedError", "GroupClosedError")
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")
        
def main():
    for root, dirs, files in os.walk(ROOT):
        if any(x in root for x in [".venv", "venv", "__pycache__", ".git", "alembic"]):
            continue
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                process_file(filepath)

if __name__ == "__main__":
    main()
