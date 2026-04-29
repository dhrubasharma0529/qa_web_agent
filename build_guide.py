"""Launcher: runs the deployment-guide PDF builder.

Why this exists:
The actual builder lives in Claude's session outputs folder, which has a long
nested path that the chat UI mangles when you copy/paste it. This launcher
sits in your workspace folder so you can run it with one short command.
"""
import runpy
import sys
import os

BUILDER = (
    r"C:\Users\Acer-nitro5\AppData\Roaming\Claude"
    r"\local-agent-mode-sessions"
    r"\5187f794-a95a-4427-a9c7-0fb130046f03"
    r"\3d5cf8af-b81b-465a-92cb-70476e471d41"
    r"\local_36568171-ce6a-488b-bbf5-8cfdd7062c23"
    r"\outputs\build_pdf.py"
)

OUTPUT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "QA_Web_Agent_Deployment_Guide.pdf",
)

if not os.path.exists(BUILDER):
    sys.exit(f"Builder not found: {BUILDER}")

# Forge argv so the builder picks up the desired output path
sys.argv = [BUILDER, OUTPUT]
runpy.run_path(BUILDER, run_name="__main__")
print(f"\n✓ Wrote: {OUTPUT}")
