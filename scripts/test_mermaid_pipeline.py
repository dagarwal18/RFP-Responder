    #!/usr/bin/env python3
"""
Test script for Mermaid generation, rendering, and PDF export.
"""
import os
import sys
import re
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# Ensure the project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rfp_automation.services.llm_service import llm_text_call
from scripts.md_to_pdf import convert_md_to_pdf

def run_test():
    load_dotenv()
    
    print("🤖 1. Requesting Mermaid JS from LLM...")
    prompt = """
    Write a brief executive summary of a cloud-native microservices architecture. 
    Then, provide a highly detailed Mermaid JS `flowchart TD` diagram illustrating the architecture.
    The diagram should include an API Gateway, an Auth Service, a Product Service, an Order Service, and a Database cluster.
    Enclose the Mermaid code EXACTLY within ```mermaid and ``` blocks.
    Do not use any other diagram formats.
    """
    content = llm_text_call(prompt)
    print(f"\n--- LLM Output Begin ---\n{content}\n--- LLM Output End ---\n")
    
    # 2. Extract Mermaid
    print("🔍 2. Extracting Mermaid block...")
    match = re.search(r"```mermaid\s*(.*?)\s*```", content, re.DOTALL)
    if not match:
        print("❌ Failed to find Mermaid block in LLM response.")
        return
        
    mermaid_code = match.group(1).strip()
    
    # 3. Setup test directory
    test_dir = Path("storage/test_mermaid")
    test_dir.mkdir(parents=True, exist_ok=True)
    
    mmd_path = test_dir / "test_diagram.mmd"
    png_path = test_dir / "test_diagram.png"
    md_path = test_dir / "test_proposal.md"
    pdf_path = test_dir / "test_proposal.pdf"
    
    mmd_path.write_text(mermaid_code, encoding="utf-8")
    print(f"✅ Saved mermaid code to {mmd_path}")
    
    # 4. Render using npx and mermaid-cli
    print("🎨 3. Rendering PNG via mermaid-cli (npx)...")
    # Using npx ensures we get the mmdc library even if not installed globally
    cmd = [
        "npx", "--yes", "@mermaid-js/mermaid-cli@10.8.0",
        "-i", str(mmd_path.absolute()),
        "-o", str(png_path.absolute()),
        "--width", "1200",
        "--backgroundColor", "white",
        "--theme", "default"
    ]
    
    try:
        # Use shell=True on windows if npx isn't found in PATH directly
        subprocess.run(
            cmd, 
            check=True, 
            capture_output=True, 
            text=True,
            shell=(os.name == "nt")
        )
        print(f"✅ Rendered image successfully to {png_path}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Rendering failed:\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}")
        return
        
    # 5. Build Markdown
    print("📝 4. Building final markdown...")
    # Replace the mermaid block with the image reference using ABSOLUTE path
    abs_img_path = str(png_path.absolute()).replace("\\", "/")
    
    # We replace the raw markdown so the final PDF incorporates the generated image
    replacement = f"![Architecture Diagram]({abs_img_path})"
    final_md = content.replace(match.group(0), replacement)
    
    md_path.write_text(final_md, encoding="utf-8")
    
    # 6. Convert to PDF
    print("📄 5. Converting Markdown to PDF...")
    final_pdf = convert_md_to_pdf(
        input_path=str(md_path),
        output_path=str(pdf_path),
        rfp_title="Mermaid Integration Test",
        client_name="Test Client",
        company_name="Test Company",
        include_cover=True
    )
    
    print(f"\n🎉 SUCCESS! Open {final_pdf} to review the output quality.")

if __name__ == "__main__":
    run_test()
