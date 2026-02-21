import os
from pathlib import Path

def aggregate_codebase(root_dir: str, output_file: str):
    root = Path(root_dir)
    exclude_dirs = {'.venv', '.git', '__pycache__', 'storage', 'Documentation', '.pytest_cache'}
    exclude_extensions = {'.pyc', '.pdf', '.png', '.jpg', '.jpeg', '.zip', '.tar', '.gz'}
    
    with open(output_file, 'w', encoding='utf-8') as out:
        out.write("# RFP Responder Codebase Dump\n\n")
        
        for dirpath, dirnames, filenames in os.walk(root):
            # Exclude directories
            dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
            
            for file in filenames:
                file_path = Path(dirpath) / file
                
                # Exclude specific extensions
                if file_path.suffix.lower() in exclude_extensions:
                    continue
                # Exclude temporary stuff or the output file itself
                if file == 'aggregate_code.py' or file == 'current_implementation.md':
                    continue
                
                rel_path = file_path.relative_to(root)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # Determine markdown language
                    ext = file_path.suffix.lower()
                    if ext == '.py':
                        lang = 'python'
                    elif ext == '.html':
                        lang = 'html'
                    elif ext == '.js':
                        lang = 'javascript'
                    elif ext == '.css':
                        lang = 'css'
                    elif ext == '.json':
                        lang = 'json'
                    elif ext == '.md':
                        lang = 'markdown'
                    elif ext == '.txt':
                        lang = 'text'
                    elif ext == '.ps1':
                        lang = 'powershell'
                    elif ext == '':
                        lang = 'bash'
                    else:
                        lang = ''
                        
                    out.write(f"## File: `{rel_path}`\n\n")
                    out.write(f"```{lang}\n{content}\n```\n\n")
                except Exception as e:
                    out.write(f"## File: `{rel_path}`\n\n")
                    out.write(f"> Error reading file: {e}\n\n")

if __name__ == "__main__":
    aggregate_codebase("d:/RFP-Responder-1", "d:/RFP-Responder-1/current_implementation.md")
    print("Codebase aggregated into current_implementation.md")
