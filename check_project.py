import os
import subprocess
import sys
import datetime

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as e:
        return f"Error running '{cmd}':\n{e.output}"

def main():
    output_file = "project_status.md"
    project_root = os.path.dirname(os.path.abspath(__file__))
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("# EDITH-AI Project Status Report\n")
        f.write(f"**Generated on:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        f.write("## 1. System Information\n")
        f.write("```text\n")
        f.write(f"OS: {sys.platform}\n")
        f.write(f"Python Version: {sys.version.split()[0]}\n")
        try:
            import psutil
            f.write(f"Total RAM: {psutil.virtual_memory().total / (1024**3):.2f} GB\n")
            f.write(f"Available RAM: {psutil.virtual_memory().available / (1024**3):.2f} GB\n")
        except ImportError:
            f.write("psutil not installed (cannot read RAM stats)\n")
        
        nvidia_smi = run_cmd("nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader")
        if "Error" not in nvidia_smi:
            f.write(f"GPU Info: {nvidia_smi}\n")
        f.write("```\n\n")

        f.write("## 2. Git Status\n")
        f.write("```text\n")
        f.write(run_cmd("git status -s") or "Working directory clean or not a git repo.")
        f.write("\n```\n\n")

        f.write("## 3. Project Structure\n")
        f.write("```text\n")
        # Custom tree-like output for python files
        total_py_files = 0
        total_lines = 0
        
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__', 'venv', 'env', '.pytest_cache', 'models', 'data']]
            rel_path = os.path.relpath(root, project_root)
            if rel_path == ".":
                level = 0
            else:
                level = rel_path.count(os.sep) + 1
            
            indent = "  " * level
            f.write(f"{indent}[{os.path.basename(root)}/]\n")
            
            for file in files:
                if file.endswith('.py'):
                    total_py_files += 1
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as pf:
                            lines = len(pf.readlines())
                            total_lines += lines
                    except:
                        pass
        f.write("```\n\n")

        f.write("## 4. Codebase Statistics\n")
        f.write("```text\n")
        f.write(f"Total Python Files: {total_py_files}\n")
        f.write(f"Total Lines of Python Code: {total_lines}\n")
        f.write("```\n\n")
        
        f.write("## 5. Active Ollama Models\n")
        f.write("```text\n")
        f.write(run_cmd("ollama list") or "Ollama not running or no models found.")
        f.write("\n```\n\n")

    print(f"Project status successfully written to: {os.path.abspath(output_file)}")

if __name__ == "__main__":
    main()
