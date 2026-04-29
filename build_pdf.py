#!/usr/bin/env python3
"""Build the comprehensive QA-Web-Agent deployment guide PDF."""

import sys
from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    KeepTogether, Preformatted,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

OUT = sys.argv[1] if len(sys.argv) > 1 else "QA_Web_Agent_Deployment_Guide.pdf"
PAGE_W, PAGE_H = letter

# ============================================================
# Styles
# ============================================================
base = getSampleStyleSheet()

NAVY = HexColor('#1a3a5c')
BLUE = HexColor('#2c5282')
DARKGRAY = HexColor('#2d3748')
GRAY = HexColor('#4a5568')
LIGHTGRAY = HexColor('#cbd5e0')
BG = HexColor('#f4f4f4')
WARN_BG = HexColor('#fff7e0')
ERR_BG = HexColor('#fff0f0')
OK_BG = HexColor('#f0fdf4')

styles = {
    'title': ParagraphStyle('title', parent=base['Title'], fontSize=30,
                            alignment=TA_CENTER, textColor=NAVY, leading=36),
    'subtitle': ParagraphStyle('subtitle', parent=base['Title'], fontSize=16,
                               alignment=TA_CENTER, textColor=DARKGRAY, leading=22),
    'tag': ParagraphStyle('tag', parent=base['Italic'], fontSize=12,
                          alignment=TA_CENTER, textColor=GRAY, leading=18),
    'h1': ParagraphStyle('h1', parent=base['Heading1'], fontSize=18,
                         textColor=NAVY, spaceAfter=12, spaceBefore=18,
                         keepWithNext=True, leading=22),
    'h2': ParagraphStyle('h2', parent=base['Heading2'], fontSize=14,
                         textColor=BLUE, spaceAfter=8, spaceBefore=14,
                         keepWithNext=True, leading=18),
    'h3': ParagraphStyle('h3', parent=base['Heading3'], fontSize=11.5,
                         textColor=DARKGRAY, spaceAfter=6, spaceBefore=10,
                         keepWithNext=True, leading=15),
    'body': ParagraphStyle('body', parent=base['Normal'], fontSize=10,
                           leading=14, spaceAfter=6, alignment=TA_LEFT),
    'small': ParagraphStyle('small', parent=base['Normal'], fontSize=8.5,
                            leading=11, spaceAfter=4),
    'code': ParagraphStyle('code', parent=base['Code'], fontName='Courier',
                           fontSize=8.5, leading=11, leftIndent=8, rightIndent=8,
                           backColor=BG, borderPadding=5, spaceAfter=8,
                           spaceBefore=2),
    'note': ParagraphStyle('note', parent=base['Normal'], fontSize=9,
                           leading=12, leftIndent=10, rightIndent=10,
                           textColor=GRAY, backColor=WARN_BG, borderPadding=6,
                           spaceAfter=10, spaceBefore=4),
    'warn': ParagraphStyle('warn', parent=base['Normal'], fontSize=9,
                           leading=12, leftIndent=10, rightIndent=10,
                           textColor=DARKGRAY, backColor=ERR_BG, borderPadding=6,
                           spaceAfter=10, spaceBefore=4),
    'ok': ParagraphStyle('ok', parent=base['Normal'], fontSize=9,
                         leading=12, leftIndent=10, rightIndent=10,
                         textColor=DARKGRAY, backColor=OK_BG, borderPadding=6,
                         spaceAfter=10, spaceBefore=4),
    'tablehead': ParagraphStyle('tablehead', parent=base['Normal'],
                                fontName='Helvetica-Bold', fontSize=9,
                                textColor=white, leading=11),
    'tablebody': ParagraphStyle('tablebody', parent=base['Normal'],
                                fontSize=9, leading=11),
    'tablecode': ParagraphStyle('tablecode', parent=base['Normal'],
                                fontName='Courier', fontSize=8.2, leading=10),
    'caption': ParagraphStyle('caption', parent=base['Italic'], fontSize=8.5,
                              textColor=GRAY, alignment=TA_CENTER,
                              spaceAfter=10),
}

def H1(t): return Paragraph(t, styles['h1'])
def H2(t): return Paragraph(t, styles['h2'])
def H3(t): return Paragraph(t, styles['h3'])
def P(t): return Paragraph(t, styles['body'])
def Note(t): return Paragraph(t, styles['note'])
def Warn(t): return Paragraph(t, styles['warn'])
def Ok(t): return Paragraph(t, styles['ok'])
def Caption(t): return Paragraph(t, styles['caption'])
def Code(text):
    return Preformatted(text, styles['code'])
def Sp(h=8): return Spacer(1, h)
def PB(): return PageBreak()

def Tbl(rows, col_widths=None, header=True, cell_style=None):
    cs = cell_style or styles['tablebody']
    wrapped = []
    for i, row in enumerate(rows):
        new = []
        for cell in row:
            if isinstance(cell, str):
                if i == 0 and header:
                    new.append(Paragraph(cell, styles['tablehead']))
                else:
                    new.append(Paragraph(cell, cs))
            else:
                new.append(cell)
        wrapped.append(new)
    t = Table(wrapped, colWidths=col_widths, repeatRows=1 if header else 0)
    cmds = [
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-1), 0.5, LIGHTGRAY),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]
    if header:
        cmds.append(('BACKGROUND', (0,0), (-1,0), BLUE))
    t.setStyle(TableStyle(cmds))
    return t

def draw_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(GRAY)
    canvas.drawString(0.75*inch, 0.5*inch, "QA-Web-Agent Deployment Guide")
    canvas.drawRightString(PAGE_W - 0.75*inch, 0.5*inch,
                           f"Page {doc.page}")
    canvas.line(0.75*inch, 0.65*inch, PAGE_W - 0.75*inch, 0.65*inch)
    canvas.restoreState()

# ============================================================
# CONTENT BUILDERS
# ============================================================

def build_title_page(s):
    s.append(Spacer(1, 1.8*inch))
    s.append(Paragraph("QA Web Agent", styles['title']))
    s.append(Spacer(1, 0.2*inch))
    s.append(Paragraph("Complete Deployment Documentation", styles['subtitle']))
    s.append(Spacer(1, 0.4*inch))
    s.append(Paragraph(
        "AWS EC2 &nbsp;&middot;&nbsp; Docker &nbsp;&middot;&nbsp; Cloudflare &nbsp;&middot;&nbsp; GitHub Actions CI/CD",
        styles['tag']))
    s.append(Spacer(1, 1.5*inch))
    s.append(Paragraph(
        "<b>Author:</b> Dhrubas Sharma<br/>"
        "<b>Domain:</b> www.dhrubas.com.np<br/>"
        "<b>Repo:</b> github.com/dhrubasharma0529/qa_web_agent<br/>"
        "<b>Stack:</b> LangGraph + FastAPI + Playwright + Cypress<br/>"
        "<b>Generated:</b> April 2026",
        ParagraphStyle('footer_meta', parent=styles['body'],
                       alignment=TA_CENTER, leading=18, textColor=GRAY)
    ))
    s.append(PB())


def build_toc(s):
    s.append(H1("Contents"))
    items = [
        ("1.  Project Overview", "3"),
        ("2.  Deployment Journey", "6"),
        ("       Phase 0 - AWS Pre-flight", "7"),
        ("       Phase 1 - Local Repo Cleanup", "10"),
        ("       Phase 2 - GitHub Repository", "15"),
        ("       Phase 3 - EC2 Instance", "18"),
        ("       Phase 4 - Live Deploy", "23"),
        ("       Phase 5 - GitHub Actions CI/CD", "30"),
        ("3.  Linux Command Reference", "35"),
        ("4.  CI/CD Configuration", "48"),
        ("5.  Error Catalog &amp; Solutions", "52"),
        ("6.  Operational Runbook", "58"),
        ("7.  Glossary", "62"),
    ]
    rows = [[Paragraph(t, styles['body']),
             Paragraph(p, ParagraphStyle('toc_pg', parent=styles['body'],
                                          alignment=TA_CENTER))]
            for t, p in items]
    t = Table(rows, colWidths=[5.2*inch, 0.8*inch])
    t.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 2),
        ('RIGHTPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LINEBELOW', (0,0), (-1,-1), 0.25, LIGHTGRAY),
    ]))
    s.append(t)
    s.append(Sp(20))
    s.append(P("This document is the living record of how qa-web-agent was taken "
               "from a local-only project to a publicly-served, CI/CD-deployed "
               "production system. It is structured so any single section can be "
               "read on its own, or you can read the deployment journey "
               "sequentially as a walkthrough."))
    s.append(PB())


def build_overview(s):
    s.append(H1("1. Project Overview"))
    s.append(H2("What this is"))
    s.append(P(
        "<b>qa-web-agent</b> is an autonomous multi-agent QA testing platform. "
        "Given a URL and a Product Requirements Document (PRD), it crawls the site, "
        "generates a hierarchical test plan, writes Cypress test specs, runs them, "
        "self-heals broken selectors, and produces a structured Markdown bug report."))
    s.append(P(
        "It is built on <b>LangGraph</b> for multi-agent orchestration, "
        "<b>LangChain-OpenAI</b> for LLM reasoning (defaulting to gpt-4o-mini), "
        "<b>Playwright</b> for browser crawling, and <b>Cypress</b> for test execution. "
        "The web tier is <b>FastAPI</b> with Server-Sent Events streaming the agent's "
        "progress live to a single-page UI."))
    s.append(H2("Where it runs in production"))
    s.append(P(
        "A single AWS EC2 t3.small in <b>ap-south-1</b> (Mumbai), running Docker. "
        "Cloudflare provides DNS, TLS termination, and a CDN/proxy in front of the origin. "
        "GitHub Actions handles CI on PRs and SSH-based deploy on every push to main."))
    s.append(H2("Stack at a glance"))
    s.append(Tbl([
        ["Layer", "Choice", "Why"],
        ["Compute", "EC2 t3.small (Ubuntu 22.04)", "Cheapest size with enough RAM (2 GB) to run Chromium + Cypress."],
        ["Container", "Docker + docker compose", "Reproducible build, isolates Python + Node + Playwright system libs."],
        ["Web server / proxy", "Nginx on host", "Stable boundary, terminates TLS, handles SSE-aware buffering."],
        ["App framework", "FastAPI + Uvicorn (Python 3.11)", "Async, supports SSE streaming, fits LangGraph idioms."],
        ["Orchestration", "LangGraph StateGraph", "5 agent nodes (Architect, Strategist, SDET, Executor, Reporter)."],
        ["LLM", "OpenAI gpt-4o-mini", "Best speed/cost trade-off for this volume of agent runs."],
        ["Browser", "Playwright (Chromium)", "Fast, well-maintained, async API."],
        ["E2E test runner", "Cypress 15.x", "Industry standard; strong selectors, video, screenshots."],
        ["State persistence", "AsyncSqliteSaver", "Per-thread checkpoint, no DB infra needed."],
        ["Source control", "GitHub (public repo)", "Free Actions minutes, works with branch protection."],
        ["DNS / TLS / CDN", "Cloudflare (Full-strict + Origin Cert)", "Free SSL, DDoS shield, hides origin IP, no certbot maintenance."],
        ["CI/CD", "GitHub Actions + appleboy/ssh-action", "Native to GitHub; SSH-based deploy is simple and auditable."],
    ], col_widths=[1.4*inch, 2.0*inch, 3.0*inch]))
    s.append(H2("Network / data flow (live request)"))
    s.append(P(
        "<b>Browser</b> -> HTTPS to <b>Cloudflare edge</b> (TLS termination, WAF, cache) -> "
        "HTTPS origin pull to <b>EC2 Elastic IP</b> -> <b>Nginx</b> on the host (port 443, "
        "Cloudflare Origin Certificate, SSE-aware proxy settings) -> loopback HTTP to "
        "<b>Uvicorn</b> on 127.0.0.1:8000 inside the Docker container -> "
        "<b>FastAPI</b> route handler -> <b>LangGraph</b> graph -> "
        "agents call <b>OpenAI</b> outbound and spawn <b>Cypress</b> as a subprocess. "
        "Streaming responses (SSE) traverse the same path in reverse, with Nginx "
        "configured for unbuffered, long-lived connections."))
    s.append(H2("Boundaries / trust rings"))
    s.append(P(
        "Public internet -> Cloudflare WAF -> AWS Security Group "
        "(SSH/22 open after CI/CD setup, HTTP/80 + HTTPS/443 from world) -> "
        "Nginx process on the host -> loopback-only proxy to the container "
        "(127.0.0.1:8000, never bound on a public interface) -> "
        "FastAPI app reading secrets from .env (<i>chmod 600</i>) at startup. "
        "Each ring fails closed: a breach in one does not automatically grant access to the next."))
    s.append(H2("What this guide deliberately does NOT cover"))
    s.append(P(
        "Per the project's CLAUDE.md (simplicity-first principle), this stack is "
        "deliberately <i>boring and small</i>. Out of scope: ECS/Kubernetes, Terraform, "
        "multi-region, RDS, ALB, autoscaling, staging environments, monitoring stacks. "
        "All of these earn their place only when scale or compliance demands. Until then, "
        "they are complexity without benefit."))
    s.append(PB())


def build_phase_overview_page(s):
    s.append(H1("2. The Deployment Journey"))
    s.append(P(
        "Every step below was performed top-to-bottom on a real account. Each "
        "phase has explicit success criteria; do not move to the next phase "
        "until the current one verifies. The journey is roughly six hours of "
        "calendar time, most of which is waiting for Docker builds and DNS "
        "propagation. The hands-on time is closer to two."))
    s.append(Sp(10))
    s.append(Tbl([
        ["Phase", "What it produces", "Approx. time"],
        ["0 - AWS Pre-flight", "Hardened AWS account: MFA, IAM user, region, OpenAI budget cap.", "30 minutes"],
        ["1 - Local Cleanup", ".gitignore, .dockerignore, .env.example, pytest, headless Cypress.", "1.5 hours"],
        ["2 - GitHub", "Public repo, branch protection, SSH key on GitHub.", "30 minutes"],
        ["3 - EC2", "Running t3.small in Mumbai, Docker installed, SSH-able.", "1 hour"],
        ["4 - Live deploy", "Container running on EC2 behind Nginx behind Cloudflare with HTTPS.", "2 hours"],
        ["5 - CI/CD", "ci.yml + deploy.yml; push-to-main auto-deploys.", "1 hour"],
    ], col_widths=[1.5*inch, 4.0*inch, 1.0*inch]))
    s.append(PB())


def build_phase_0(s):
    s.append(H1("Phase 0 - AWS Pre-flight"))
    s.append(P("Goal: harden the AWS account before launching any compute."))
    s.append(H2("0.1 - MFA on AWS root account"))
    s.append(P("Sign in to console.aws.amazon.com as root. Top-right account name -> "
               "Security credentials -> Multi-factor authentication (MFA) -> Assign MFA device. "
               "Choose Authenticator app, scan the QR code with Google Authenticator / "
               "Microsoft Authenticator / Authy / 1Password, enter two consecutive codes."))
    s.append(P("Verify: sign out and back in. The login should now ask for an MFA code."))
    s.append(Note("Avoid SMS-based MFA - SIM-swap attacks have made it untrustworthy. "
                  "TOTP authenticator apps are the right choice."))
    s.append(H2("0.2 - Create an IAM user for daily use"))
    s.append(P("IAM service -> Users -> Create user. Username e.g. <i>dhrubas123</i>. "
               "Tick 'Provide user access to the AWS Management Console'. "
               "Choose 'I want to create an IAM user'. Set a strong password. "
               "Permissions: 'Attach policies directly' -> AdministratorAccess. "
               "Save the URL + username + password (shown once). Enable MFA on this IAM user too."))
    s.append(H2("0.3 - Pick AWS region"))
    s.append(P("Top-right region selector -> <b>Asia Pacific (Mumbai) ap-south-1</b>. "
               "Closest AWS region to Nepal (~30-60 ms RTT)."))
    s.append(H2("0.4 - OpenAI key and budget"))
    s.append(P("platform.openai.com -> Settings -> Billing: confirm payment method. "
               "Settings -> Limits: hard limit $20, soft threshold $10. "
               "API keys -> Create new secret key, save in password manager. "
               "Default model: <i>gpt-4o-mini</i> (gpt-4o is ~10x the price)."))
    s.append(PB())


def build_phase_1(s):
    s.append(H1("Phase 1 - Local Repository Cleanup"))
    s.append(H2("1.1 - Delete junk from the working tree"))
    s.append(Code(
        "cd C:\\Users\\Acer-nitro5\\Downloads\\qa-agent-dhur\n"
        "Remove-Item -Recurse -Force .\\__MACOSX\n"
        "Get-ChildItem -Path .\\src -Recurse -Force -Directory `\n"
        "  -Filter \"__pycache__\" | Remove-Item -Recurse -Force\n"
        "Remove-Item -Force .\\checkpoints.db, .\\checkpoints.db-shm, `\n"
        "  .\\checkpoints.db-wal -ErrorAction SilentlyContinue\n"
        "Remove-Item -Recurse -Force .\\cypress\\screenshots\\* `\n"
        "  -ErrorAction SilentlyContinue\n"
        "Remove-Item -Force .\\reports\\*.md -ErrorAction SilentlyContinue"))
    s.append(P("<b>What is NOT deleted:</b> qaenv/ - your local Python venv, "
               "kept on disk and just gitignored."))
    s.append(H2("1.2 - Write the .gitignore"))
    s.append(Code(
        "# Environment / secrets\n"
        ".env\n"
        ".env.*\n"
        "!.env.example\n"
        "\n"
        "# Python\n"
        "__pycache__/\n"
        "*.py[cod]\n"
        ".venv/\n"
        "venv/\n"
        "qaenv/\n"
        ".pytest_cache/\n"
        "\n"
        "# Node / Cypress\n"
        "node_modules/\n"
        "cypress/screenshots/\n"
        "cypress/videos/\n"
        "\n"
        "# LangGraph runtime\n"
        "checkpoints.db\n"
        "*.db-shm\n"
        "*.db-wal\n"
        "\n"
        "# OS / IDE\n"
        ".DS_Store\n"
        "Thumbs.db\n"
        "__MACOSX/\n"
        ".vscode/\n"
        ".idea/"))
    s.append(Note("The <i>!.env.example</i> rule is the negation pattern - it keeps the "
                  "template committable while .env stays private."))
    s.append(H2("1.3 - Cypress headless config"))
    s.append(P("The executor reads <i>config.CYPRESS_HEADED</i>, which defaults to "
               "<i>False</i> (headless). On a headless Linux server this default is correct; "
               "no code change is needed."))
    s.append(H2("1.4 - Sanitise .env.example"))
    s.append(Code(
        "OPENAI_API_KEY=sk-proj-REPLACE_ME\n"
        "OPENAI_MODEL=gpt-4o-mini\n"
        "LLM_MODEL=gpt-4o-mini\n"
        "LANGSMITH_TRACING=true\n"
        "LANGSMITH_PROJECT=qa-web-agent\n"
        "LANGSMITH_API_KEY=lsv2_pt_REPLACE_ME\n"
        "BROWSER_BACKEND=playwright\n"
        "CYPRESS_HEADED=false\n"
        "CYPRESS_STEP_DELAY_MS=0\n"
        "CHECKPOINTER=sqlite\n"
        "SQLITE_DB_PATH=checkpoints.db\n"
        "BG_JOB_ISOLATED_LOOPS=true\n"
        "TARGET_ENV=cloud"))
    s.append(H2("1.5 - Local Docker smoke test"))
    s.append(Code(
        "docker compose up --build       # 5-15 min first build\n"
        "# wait for: \"Application startup complete\"\n"
        "# in browser: http://localhost:8000\n"
        "docker compose down              # stop cleanly when done"))
    s.append(H2("1.6 - Add a pytest sanity test"))
    s.append(Code(
        "# tests/test_health.py\n"
        "import pytest\n"
        "from src.server import health\n"
        "\n"
        "@pytest.mark.asyncio\n"
        "async def test_health_returns_ok():\n"
        "    result = await health()\n"
        "    assert result == {\"status\": \"ok\"}"))
    s.append(Code(
        "# pytest.ini\n"
        "[pytest]\n"
        "testpaths = tests\n"
        "asyncio_mode = strict"))
    s.append(Code(
        "# requirements-dev.txt\n"
        "-r requirements.txt\n"
        "pytest>=8.0\n"
        "pytest-asyncio>=0.23"))
    s.append(P("Run locally: <i>python -m pytest -q</i>. The <i>python -m</i> form "
               "forces the venv's pytest, sidestepping Windows PATH ambiguity."))
    s.append(H2("1.7 - Write the .dockerignore"))
    s.append(Code(
        ".env\n"
        "qaenv/\n"
        ".venv/\n"
        "__pycache__/\n"
        "*.py[cod]\n"
        "node_modules/\n"
        "cypress/screenshots/\n"
        "cypress/videos/\n"
        "checkpoints.db*\n"
        "reports/*.md\n"
        ".git/\n"
        ".vscode/\n"
        ".idea/\n"
        "__MACOSX/\n"
        "Dockerfile\n"
        "docker-compose.yml\n"
        ".dockerignore"))
    s.append(P("Without this, Docker copies qaenv/ (~500 MB of Windows-built .pyd files) "
               "into the build context. Build time + image size suffer."))
    s.append(PB())


def build_phase_2(s):
    s.append(H1("Phase 2 - GitHub Repository"))
    s.append(H2("2.1 - Configure git identity"))
    s.append(Code(
        "git config --global user.name \"Dhrubas\"\n"
        "git config --global user.email \"your-personal@email.com\"\n"
        "git config --global init.defaultBranch main\n"
        "git config --global pull.rebase false"))
    s.append(H2("2.2 - git init + safety check + first commit"))
    s.append(Code(
        "cd C:\\Users\\Acer-nitro5\\Downloads\\qa-agent-dhur\n"
        "git init\n"
        "git status                           # .env MUST NOT appear\n"
        "git add .\n"
        "git ls-files | Select-String \"^\\.env$\"   # MUST return nothing\n"
        "git commit -m \"initial commit\"\n"
        "git branch -M main"))
    s.append(H2("2.3 - SSH to GitHub"))
    s.append(P("Test: <i>ssh -T git@github.com</i>. If denied, generate "
               "<i>ssh-keygen -t ed25519 -C \"email\"</i>, then add the .pub to "
               "github.com/settings/keys."))
    s.append(H2("2.4 - Create the GitHub repository"))
    s.append(P("github.com/new -> name <i>qa_web_agent</i> -> <b>Public</b> "
               "(unlocks free Actions and enforced branch protection) -> "
               "do NOT initialize with README, .gitignore, or license."))
    s.append(H2("2.5 - Connect remote and push"))
    s.append(Code(
        "git remote add origin git@github.com:dhrubasharma0529/qa_web_agent.git\n"
        "git push -u origin main"))
    s.append(H2("2.6 - Branch protection"))
    s.append(P("Settings -> Branches -> Add rule. Branch: main. "
               "Tick: 'Require a pull request before merging' (leave 'Require approvals' "
               "unchecked for solo dev), 'Require linear history', "
               "'Do not allow bypassing'."))
    s.append(Note("On a free PRIVATE repo, branch protection is configurable but NOT "
                  "enforced. Public repos enforce. To enforce on private: GitHub Pro ($4/mo)."))
    s.append(H2("2.7 - Default merge style"))
    s.append(P("Settings -> General -> Pull Requests. Disable Merge commit and Rebase "
               "merging; keep only <b>Squash and merge</b>. Default the squash commit "
               "message to 'Pull request title and description'."))
    s.append(PB())


def build_phase_3(s):
    s.append(H1("Phase 3 - EC2 Instance"))
    s.append(H2("3.1 - Launch the instance"))
    s.append(Tbl([
        ["Setting", "Value"],
        ["Name", "qa-agent"],
        ["AMI", "Ubuntu Server 22.04 LTS, x86_64"],
        ["Instance type", "<b>t3.small</b> (2 vCPU, 2 GB)"],
        ["Key pair", "Create new <i>qa-agent-key</i> (ED25519, .pem)"],
        ["Auto-assign public IP", "Enable"],
        ["Storage", "20 GB gp3"],
        ["Region", "ap-south-1 (Mumbai)"],
    ], col_widths=[2.0*inch, 4.5*inch]))
    s.append(H3("Security group inbound rules"))
    s.append(Tbl([
        ["Type", "Port", "Source"],
        ["SSH", "22", "My IP (initially)"],
        ["HTTP", "80", "0.0.0.0/0"],
        ["HTTPS", "443", "0.0.0.0/0"],
    ], col_widths=[1.5*inch, 1.0*inch, 4.0*inch]))
    s.append(H2("3.2 - Allocate and associate Elastic IP"))
    s.append(P("EC2 -> Elastic IPs -> Allocate -> Associate with the qa-agent instance. "
               "An EIP is yours until you release it; survives reboot/stop/rebuild."))
    s.append(Note("AWS charges ~$3.60/mo per public IPv4 since Feb 2024. "
                  "Don't release the EIP unless you're tearing down the project."))
    s.append(H2("3.3 - First SSH connection"))
    s.append(Code(
        "Move-Item \"$env:USERPROFILE\\Downloads\\qa-agent-key.pem\" `\n"
        "          \"$env:USERPROFILE\\.ssh\\qa-agent-key.pem\"\n"
        "$key = \"$env:USERPROFILE\\.ssh\\qa-agent-key.pem\"\n"
        "icacls $key /inheritance:r\n"
        "icacls $key /grant:r \"$($env:USERNAME):(R)\"\n"
        "ssh -i $env:USERPROFILE\\.ssh\\qa-agent-key.pem ubuntu@<EIP>"))
    s.append(P("SSH config alias - put in C:\\Users\\Acer-nitro5\\.ssh\\config:"))
    s.append(Code(
        "Host qa-agent\n"
        "    HostName 3.109.177.194\n"
        "    User ubuntu\n"
        "    IdentityFile ~/.ssh/qa-agent-key.pem\n"
        "    StrictHostKeyChecking accept-new"))
    s.append(P("Then <i>ssh qa-agent</i> works as a one-word command."))
    s.append(H2("3.4 - Install Docker on the instance"))
    s.append(Code(
        "# 1. base utilities\n"
        "sudo apt update && sudo apt upgrade -y\n"
        "sudo apt install -y ca-certificates curl gnupg git nginx ufw htop\n"
        "\n"
        "# 2. Docker GPG key\n"
        "sudo install -m 0755 -d /etc/apt/keyrings\n"
        "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \\\n"
        "  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg\n"
        "sudo chmod a+r /etc/apt/keyrings/docker.gpg\n"
        "\n"
        "# 3. Docker apt repository\n"
        "echo \"deb [arch=$(dpkg --print-architecture) \\\n"
        "  signed-by=/etc/apt/keyrings/docker.gpg] \\\n"
        "  https://download.docker.com/linux/ubuntu \\\n"
        "  $(. /etc/os-release && echo $VERSION_CODENAME) stable\" | \\\n"
        "  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null\n"
        "sudo apt update\n"
        "\n"
        "# 4. Docker engine + Compose plugin\n"
        "sudo apt install -y docker-ce docker-ce-cli containerd.io \\\n"
        "  docker-buildx-plugin docker-compose-plugin\n"
        "\n"
        "# 5. let ubuntu run docker without sudo\n"
        "sudo usermod -aG docker ubuntu\n"
        "exit\n"
        "# (re-SSH for the group change to take effect)"))
    s.append(H2("3.5 - Sanity check"))
    s.append(Code("docker run --rm hello-world"))
    s.append(PB())


def build_phase_4(s):
    s.append(H1("Phase 4 - Live Deploy"))
    s.append(H2("4.1 - Clone the repo onto EC2"))
    s.append(Code(
        "mkdir -p /home/ubuntu/apps\n"
        "cd /home/ubuntu/apps\n"
        "git clone https://github.com/dhrubasharma0529/qa_web_agent.git\n"
        "cd qa_web_agent\n"
        "ls .env 2>/dev/null && echo BAD || echo OK    # MUST print OK"))
    s.append(H2("4.2 - Create .env on EC2"))
    s.append(Code(
        "# from a NEW PowerShell on your laptop\n"
        "scp C:\\Users\\Acer-nitro5\\Downloads\\qa-agent-dhur\\.env `\n"
        "    qa-agent:/home/ubuntu/apps/qa_web_agent/.env"))
    s.append(Code(
        "# on EC2\n"
        "cd /home/ubuntu/apps/qa_web_agent\n"
        "chmod 600 .env\n"
        "ls -l .env                         # mode -rw-------\n"
        "echo \"CYPRESS_STEP_DELAY_MS=0\" >> .env"))
    s.append(H2("4.3 - Build and run"))
    s.append(Code(
        "docker compose build              # 10-15 min on t3.small\n"
        "docker compose up -d\n"
        "docker compose ps\n"
        "docker compose logs -f --tail=80\n"
        "curl http://localhost:8000/health"))
    s.append(P("If OOM during build, add 2 GB swap:"))
    s.append(Code(
        "sudo fallocate -l 2G /swapfile\n"
        "sudo chmod 600 /swapfile\n"
        "sudo mkswap /swapfile\n"
        "sudo swapon /swapfile\n"
        "echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab"))
    s.append(H2("4.4 - Nginx reverse proxy"))
    s.append(Code(
        "sudo tee /etc/nginx/sites-available/qa-agent > /dev/null <<'EOF'\n"
        "server {\n"
        "    listen 80 default_server;\n"
        "    listen [::]:80 default_server;\n"
        "    server_name _;\n"
        "    return 301 https://$host$request_uri;\n"
        "}\n"
        "server {\n"
        "    listen 443 ssl default_server;\n"
        "    listen [::]:443 ssl default_server;\n"
        "    http2 on;\n"
        "    server_name www.dhrubas.com.np dhrubas.com.np _;\n"
        "    ssl_certificate     /etc/ssl/qa-agent/origin.crt;\n"
        "    ssl_certificate_key /etc/ssl/qa-agent/origin.key;\n"
        "    ssl_protocols       TLSv1.2 TLSv1.3;\n"
        "    client_max_body_size 10m;\n"
        "    location / {\n"
        "        proxy_pass http://127.0.0.1:8000;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Host              $host;\n"
        "        proxy_set_header X-Real-IP         $remote_addr;\n"
        "        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto $scheme;\n"
        "        proxy_buffering           off;\n"
        "        proxy_cache               off;\n"
        "        proxy_read_timeout        3600s;\n"
        "        proxy_send_timeout        3600s;\n"
        "        chunked_transfer_encoding on;\n"
        "    }\n"
        "}\n"
        "EOF\n"
        "sudo ln -s /etc/nginx/sites-available/qa-agent /etc/nginx/sites-enabled/qa-agent\n"
        "sudo rm /etc/nginx/sites-enabled/default\n"
        "sudo nginx -t\n"
        "sudo systemctl reload nginx"))
    s.append(P("Single-quoted <i>'EOF'</i> prevents shell expansion of <i>$host</i>, "
               "<i>$scheme</i>, etc."))
    s.append(H2("4.5 - Cloudflare DNS + Origin Certificate"))
    s.append(P("Migrate nameservers at the .np registrar from "
               "<i>ns1.vercel-dns.com / ns2.vercel-dns.com</i> to the two Cloudflare "
               "names assigned to your zone (e.g., <i>isaac.ns.cloudflare.com</i>, "
               "<i>linda.ns.cloudflare.com</i>). Wait for propagation: "
               "<i>nslookup -type=NS dhrubas.com.np 1.1.1.1</i>."))
    s.append(P("Then in Cloudflare:"))
    s.append(P("1. DNS -> Add A record <i>www -> EIP</i> (Proxied), "
               "<i>@ -> EIP</i> (Proxied).<br/>"
               "2. SSL/TLS -> Origin Server -> Create Certificate. ECC, 15 years. "
               "Save cert + private key.<br/>"
               "3. Install on EC2:"))
    s.append(Code(
        "sudo mkdir -p /etc/ssl/qa-agent\n"
        "sudo chmod 700 /etc/ssl/qa-agent\n"
        "sudo nano /etc/ssl/qa-agent/origin.crt   # paste cert\n"
        "sudo nano /etc/ssl/qa-agent/origin.key   # paste private key\n"
        "sudo chmod 600 /etc/ssl/qa-agent/origin.key\n"
        "sudo chmod 644 /etc/ssl/qa-agent/origin.crt\n"
        "sudo nginx -t && sudo systemctl reload nginx"))
    s.append(P("4. SSL/TLS -> Overview -> <b>Full (strict)</b>. Edge Certificates: "
               "Always Use HTTPS = ON; Min TLS 1.2."))
    s.append(P("Verify in incognito: <i>https://www.dhrubas.com.np/health</i> -> "
               "<i>{\"status\":\"ok\"}</i> with green padlock."))
    s.append(PB())


def build_phase_5(s):
    s.append(H1("Phase 5 - GitHub Actions CI/CD"))
    s.append(H2("5.0 - Open SSH for the GitHub runner"))
    s.append(P("EC2 -> Security Groups -> qa-agent-sg -> change SSH (22) source from "
               "<i>My IP</i> to <i>Anywhere-IPv4 (0.0.0.0/0)</i>. Verify key-only auth first:"))
    s.append(Code("sudo sshd -T | grep -i passwordauth\n"
                  "# must say: passwordauthentication no"))
    s.append(P("Optional hardening:"))
    s.append(Code(
        "sudo apt install -y fail2ban\n"
        "sudo systemctl enable --now fail2ban"))
    s.append(H2("5.1 - GitHub Actions secrets"))
    s.append(P("Repo -> Settings -> Secrets and variables -> Actions. Add three:"))
    s.append(Tbl([
        ["Name", "Value"],
        ["EC2_HOST", "your Elastic IP"],
        ["EC2_USER", "ubuntu"],
        ["EC2_SSH_KEY", "Full contents of qa-agent-key.pem (BEGIN/END included)"],
    ], col_widths=[1.6*inch, 4.9*inch]))
    s.append(Code(
        "Get-Content $env:USERPROFILE\\.ssh\\qa-agent-key.pem -Raw | Set-Clipboard"))
    s.append(H2("5.2 - CI workflow (.github/workflows/ci.yml)"))
    s.append(Code(
        "name: CI\n"
        "on:\n"
        "  pull_request:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: \"3.11\"\n"
        "          cache: pip\n"
        "          cache-dependency-path: requirements-dev.txt\n"
        "      - run: |\n"
        "          python -m pip install --upgrade pip\n"
        "          python -m pip install -r requirements-dev.txt\n"
        "      - run: pytest -q"))
    s.append(H2("5.3 - Deploy workflow (.github/workflows/deploy.yml)"))
    s.append(Code(
        "name: Deploy\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: \"3.11\"\n"
        "          cache: pip\n"
        "      - run: python -m pip install -r requirements-dev.txt\n"
        "      - run: pytest -q\n"
        "  deploy:\n"
        "    needs: test\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: appleboy/ssh-action@v1\n"
        "        with:\n"
        "          host: ${{ secrets.EC2_HOST }}\n"
        "          username: ${{ secrets.EC2_USER }}\n"
        "          key: ${{ secrets.EC2_SSH_KEY }}\n"
        "          command_timeout: 30m\n"
        "          script: |\n"
        "            set -euo pipefail\n"
        "            cd /home/ubuntu/apps/qa_web_agent\n"
        "            git pull --ff-only origin main\n"
        "            docker compose build\n"
        "            docker compose up -d\n"
        "            docker image prune -f\n"
        "            sleep 8\n"
        "            curl --fail --silent http://localhost:8000/health"))
    s.append(H2("5.4 - Ship via PR"))
    s.append(Code(
        "git checkout -b ci/add-github-actions\n"
        "git add .github/workflows/ci.yml .github/workflows/deploy.yml\n"
        "git commit -m \"ci: add GitHub Actions CI + deploy workflows\"\n"
        "git push -u origin ci/add-github-actions"))
    s.append(P("Open the PR -> CI runs green -> Squash and merge -> Deploy run starts -> "
               "first run takes ~10 min for the EC2 build."))
    s.append(PB())


def build_linux_commands(s):
    s.append(H1("3. Linux Command Reference"))
    s.append(P("Every command used during deployment, with description and reason."))

    sections = [
        ("3.1 Survival kit (use daily)", [
            ["pwd", "Print working directory.", "Always know where you are."],
            ["ls -lah", "List long, all hidden, human sizes.", "Default ls hides dotfiles."],
            ["cd &lt;dir&gt;", "Change directory.", "<i>cd -</i> previous; <i>cd</i> alone = home."],
            ["cat &lt;file&gt;", "Print full file.", "Quickest peek; for big files use less."],
            ["less &lt;file&gt;", "Paged viewer; q to quit.", "Doesn't load whole file."],
            ["nano &lt;file&gt;", "Simple editor; Ctrl+O save, Ctrl+X quit.", "Beginner-friendly."],
            ["sudo &lt;cmd&gt;", "Run as root.", "Required for system-level changes."],
            ["man &lt;cmd&gt;", "Manual page; q to quit.", "Authoritative docs."],
            ["history", "Show past commands; !42 re-runs.", "Recall + replay."],
            ["clear / Ctrl+L", "Clear screen.", "Fresh start."],
        ]),
        ("3.2 Files, directories, permissions", [
            ["mkdir -p path", "Create dir + parents.", "Idempotent."],
            ["touch &lt;file&gt;", "Create empty / update mtime.", "Placeholder."],
            ["cp &lt;src&gt; &lt;dst&gt;", "Copy.", "<i>-r</i> for dirs."],
            ["mv &lt;src&gt; &lt;dst&gt;", "Move OR rename.", "Same syscall."],
            ["rm &lt;file&gt;", "Delete file. NO UNDO.", "<i>-rf</i> on a folder is dangerous."],
            ["ln -s target link", "Symbolic link.", "Used by nginx sites-enabled."],
            ["chmod NNN &lt;file&gt;", "Permissions: r=4, w=2, x=1, summed.", "<i>chmod 600 .env</i>"],
            ["chown user:group &lt;file&gt;", "Change ownership.", "Fix root-owned files."],
            ["stat &lt;file&gt;", "Detailed metadata.", "More than ls -l."],
        ]),
        ("3.3 SSH and remote", [
            ["ssh user@host", "Open shell on remote.", "Foundation."],
            ["ssh -i key.pem user@host", "With specific key.", "AWS .pem files."],
            ["scp src remote:dest", "Copy to remote.", ".env to EC2."],
            ["scp -r remote:dir local", "Recursive pull.", "Fetch logs."],
            ["ssh remote 'cmd'", "One-shot remote command.", "Scripted ops."],
            ["ssh-keygen -t ed25519 -C 'email'", "Generate key.", "Modern, small."],
            ["ssh-copy-id user@host", "Append pubkey to remote authorized_keys.", "Skip manual paste."],
            ["~/.ssh/config", "Per-host alias.", "<i>ssh qa-agent</i> shorthand."],
        ]),
        ("3.4 apt", [
            ["sudo apt update", "Refresh catalog.", "Before install/upgrade."],
            ["sudo apt upgrade -y", "Install newer versions.", "After update."],
            ["sudo apt install -y &lt;pkg&gt;", "Install package.", "Multiple OK."],
            ["sudo apt remove &lt;pkg&gt;", "Uninstall, keep config.", "Re-install later."],
            ["sudo apt purge &lt;pkg&gt;", "Uninstall + delete config.", "Clean."],
            ["sudo apt autoremove", "Remove orphans.", "After many removes."],
            ["apt list --installed | grep X", "Is X installed?", "Quick check."],
            ["which &lt;cmd&gt;", "Which binary runs?", "PATH ambiguity."],
        ]),
        ("3.5 systemd", [
            ["sudo systemctl start svc", "Start now.", ""],
            ["sudo systemctl stop svc", "Stop now.", ""],
            ["sudo systemctl restart svc", "Stop+start.", "After most config changes."],
            ["sudo systemctl reload svc", "Re-read config no drops.", "Nginx supports it."],
            ["sudo systemctl status svc", "Running? recent logs?", "First diagnostic."],
            ["sudo systemctl enable svc", "Start on boot.", "Survive reboot."],
            ["sudo systemctl daemon-reload", "Re-read unit files.", "After editing unit."],
            ["journalctl -u svc", "Logs for unit.", "<i>-f -n100 -p err</i>."],
            ["ps aux | grep X", "Find process.", "Quick grep."],
            ["pgrep -af X", "Cleaner alternative.", "Returns PIDs+cmd."],
            ["kill &lt;pid&gt;", "SIGTERM (graceful).", ""],
            ["kill -9 &lt;pid&gt;", "SIGKILL (force).", "Last resort."],
            ["lsof -i :8000", "Process using port.", "'Address in use'."],
            ["ss -tlnp", "Listening TCP + procs.", "Modern netstat."],
        ]),
        ("3.6 Networking", [
            ["curl -i URL", "GET + headers.", "Health checks."],
            ["curl -I URL", "HEAD only.", ""],
            ["curl -v URL", "Verbose; TLS handshake.", "Debug HTTPS."],
            ["curl --fail --silent URL", "Fail on 4xx/5xx.", "CI scripts."],
            ["curl -X POST -d '{...}'", "POST a body.", "Drive endpoints."],
            ["dig HOST", "DNS lookup full.", "<i>+short -type=NS</i>."],
            ["nslookup HOST 1.1.1.1", "Specific resolver.", "Avoid cache."],
            ["ping -c 4 HOST", "ICMP echo 4 packets.", "Box alive?"],
            ["ip a", "Interfaces, IPs.", "Find internal IP."],
            ["curl -s ifconfig.me", "Public IP.", "From any host."],
            ["sudo ufw allow 22/tcp", "Open host firewall.", "Optional layer."],
        ]),
        ("3.7 Nginx", [
            ["sudo nginx -t", "Validate config.", "ALWAYS before reload."],
            ["sudo systemctl reload nginx", "Apply no drops.", "Preferred."],
            ["/etc/nginx/sites-available/", "Configs (dormant).", "Convention."],
            ["/etc/nginx/sites-enabled/", "Active = symlinks.", "Activate via ln."],
            ["/var/log/nginx/access.log", "Every request.", "Debug starts here."],
            ["/var/log/nginx/error.log", "Errors + upstream.", "502 cause."],
        ]),
        ("3.8 Docker / Compose", [
            ["docker compose build", "Build images.", "Reuses cached layers."],
            ["docker compose up -d", "Start detached.", "Survives logout."],
            ["docker compose down", "Stop + remove.", "Image stays."],
            ["docker compose ps", "Service status.", "First check."],
            ["docker compose logs -f --tail=50", "Live tail.", "Boot debug."],
            ["docker compose restart svc", "Restart one.", "Pick up env change."],
            ["docker ps", "Running containers.", ""],
            ["docker images", "All local images.", "Find disk hogs."],
            ["docker image prune -f", "Remove dangling.", "Every deploy."],
            ["docker system prune -a -f", "Aggressive cleanup.", "Use sparingly."],
            ["docker exec -it ctr bash", "Shell inside container.", "Debug app."],
            ["docker inspect ctr", "Full JSON.", "Started, mounts, networks."],
        ]),
        ("3.9 Disk, memory", [
            ["df -h", "Disk per mount.", "Full disk = silent failures."],
            ["du -sh *", "Size each item.", "Find big folder."],
            ["du -sh /var/log", "Log volume.", "Rotation issues."],
            ["free -h", "Memory + swap.", "OOM-kill story."],
            ["uptime", "Up + load avg.", "Health overview."],
            ["top", "Live processes.", "Always installed."],
            ["htop", "Friendlier top.", "<i>apt install htop</i>."],
            ["vmstat 1 5", "5 samples 1s.", "Transient pressure."],
            ["iostat", "Disk IO.", "<i>apt install sysstat</i>."],
        ]),
        ("3.10 Environment / users", [
            ["echo $HOME", "Print env var.", ""],
            ["env", "All env vars.", "Confirm injection."],
            ["whoami", "Current user.", ""],
            ["id", "uid, gid, groups.", "Confirm 'docker' in groups."],
            ["sudo -i", "Login as root.", "Less typing 'sudo'."],
            ["sudo usermod -aG docker ubuntu", "Add to group.", "Docker w/o sudo."],
            ["~/.bashrc", "Per-user shell rc.", "Aliases, PATH."],
            ["source ~/.bashrc", "Re-evaluate.", "After edits."],
        ]),
        ("3.11 Archives", [
            ["tar -czf out.tar.gz dir/", "gzip tar.", "Standard."],
            ["tar -xzf out.tar.gz", "Extract.", ""],
            ["tar -tzf out.tar.gz", "List contents.", "Sanity check."],
            ["zip -r out.zip dir/", "Zip.", ""],
            ["unzip out.zip", "Extract zip.", ""],
        ]),
    ]

    for title, rows in sections:
        s.append(H2(title))
        wrapped = [["Command", "What it does", "Why used here"]] + rows
        s.append(Tbl(wrapped, col_widths=[1.7*inch, 2.4*inch, 2.4*inch],
                     cell_style=styles['tablecode']))
        s.append(Sp(6))

    s.append(H2("3.12 Shortcut keys"))
    s.append(Tbl([
        ["Key", "Effect"],
        ["Tab", "Autocomplete file/command name."],
        ["Tab Tab", "List possible completions."],
        ["Ctrl+R", "Reverse-search history."],
        ["Ctrl+C", "Cancel current command."],
        ["Ctrl+D", "End of input / log out."],
        ["Ctrl+L", "Clear screen."],
        ["Ctrl+A / Ctrl+E", "Start / end of line."],
        ["Ctrl+U / Ctrl+K", "Delete to start / end."],
        ["Ctrl+W", "Delete previous word."],
        ["!! / sudo !!", "Re-run last / with sudo."],
        ["!ssh", "Re-run last 'ssh ...'."],
    ], col_widths=[1.5*inch, 5.0*inch]))

    s.append(H2("3.13 Dangerous commands"))
    s.append(Tbl([
        ["Command", "Why dangerous"],
        ["rm -rf path", "No undo. Triple-check the path."],
        ["chmod -R 777 path", "World-writable. Almost never right."],
        ["sudo dd if=... of=...", "Wrong target = destroyed disk."],
        ["&gt; file.txt", "Single &gt; truncates to empty."],
        [":(){ :|:&amp; };:", "Fork bomb. Don't type this."],
    ], col_widths=[2.0*inch, 4.5*inch]))
    s.append(PB())


def build_cicd_doc(s):
    s.append(H1("4. CI/CD Configuration"))
    s.append(H2("4.1 Why two separate workflows"))
    s.append(P("CI runs only on PRs. CD runs only on push-to-main and re-runs the same "
               "tests inside before deploying. No double runs; defense in depth."))
    s.append(H2("4.2 Secrets - what's where"))
    s.append(Tbl([
        ["Secret", "Stored in", "Used for"],
        ["EC2_HOST", "GitHub Actions secrets", "SSH host"],
        ["EC2_USER", "GitHub Actions secrets", "SSH user"],
        ["EC2_SSH_KEY", "GitHub Actions secrets", "SSH private key"],
        ["OPENAI_API_KEY", "EC2 .env (chmod 600)", "App calls"],
        ["LANGSMITH_API_KEY", "EC2 .env (chmod 600)", "Tracing"],
        ["TLS cert + key", "EC2 /etc/ssl/qa-agent/", "Nginx HTTPS"],
    ], col_widths=[1.7*inch, 2.5*inch, 2.3*inch]))
    s.append(P("App secrets live <b>only on EC2</b>. CI/CD never sees them."))
    s.append(H2("4.3 Debugging on the runner"))
    s.append(P("Re-run individual jobs from the Actions tab. Add "
               "<i>on: workflow_dispatch</i> for a manual button. Set "
               "<i>ACTIONS_RUNNER_DEBUG=true</i> secret for verbose logs. "
               "<i>act</i> (nektosact.com) runs workflows locally."))
    s.append(PB())


def build_errors(s):
    s.append(H1("5. Error Catalog &amp; Solutions"))

    sections = [
        ("5.1 SSH", [
            ["Permission denied (publickey)",
             "Wrong key, key not in authorized_keys, or pubkey not on GitHub.",
             "Verify key path; on AWS, run icacls; on GitHub, re-add pubkey."],
            ["Connection timed out",
             "SG / firewall blocking source IP.",
             "Check SG rule for 22; update <i>My IP</i> if your home IP changed."],
            ["Connection refused",
             "Port not open / sshd not running.",
             "<i>sudo systemctl status ssh</i>."],
            ["Host key verification failed",
             "Remote host key changed (instance rebuild).",
             "<i>ssh-keygen -R &lt;host&gt;</i>."],
            ["scp: Could not resolve hostname qa-agent",
             "You ran scp inside the EC2 SSH session.",
             "Run scp from a SECOND PowerShell on your laptop."],
            ["icacls fails / 'Permissions ... too open'",
             "Inherited Windows ACL.",
             "<i>icacls $key /inheritance:r</i> + grant only your user (R)."],
        ]),
        ("5.2 Docker", [
            ["Cannot connect to Docker daemon",
             "Docker Desktop / dockerd not running.",
             "Start Docker Desktop or <i>sudo systemctl start docker</i>."],
            ["WSL exec error 0xc00000fd",
             "WSL2 backend bad state.",
             "<i>wsl --shutdown</i>; restart Docker Desktop. <i>wsl --update</i>."],
            ["BuildKit RPC EOF",
             "Daemon flake post-restart.",
             "Retry. Fall back: <i>$env:DOCKER_BUILDKIT=0</i>."],
            ["Killed / Cannot allocate memory",
             "OOM on t3.small.",
             "Add 2 GB swap (Phase 4.3)."],
            ["bind 0.0.0.0:80: Address already in use",
             "Apache running.",
             "<i>sudo systemctl disable --now apache2</i>."],
            ["502 Bad Gateway",
             "Container down or wrong upstream.",
             "<i>docker compose ps</i>; check container logs."],
            ["Build context huge / slow",
             "Missing .dockerignore (qaenv/ being copied).",
             "Add .dockerignore (Phase 1.7)."],
        ]),
        ("5.3 Python / pytest", [
            ["ModuleNotFoundError: No module named 'src'",
             "tests/ not a package.",
             "Add empty <i>tests/__init__.py</i>."],
            ["Unknown config option: asyncio_mode",
             "Wrong pytest (system one without pytest-asyncio).",
             "<i>python -m pytest -q</i>."],
            ["pytest hangs forever",
             "TestClient triggered FastAPI lifespan.",
             "Call route handler directly."],
            ["pytest: command not found after pip install",
             "PATH ordering picks system Python.",
             "<i>python -m pytest -q</i>."],
            ["Activate.ps1 disabled",
             "Windows execution policy.",
             "<i>Set-ExecutionPolicy RemoteSigned -Scope CurrentUser</i>."],
        ]),
        ("5.4 Git / GitHub", [
            ["Repository not found",
             "Wrong URL or HTTPS without auth.",
             "Confirm name; switch remote to SSH."],
            ["src refspec X does not match",
             "Branch not created locally.",
             "<i>git checkout -b X</i>, then push."],
            ["Push to main rejected (protected)",
             "Branch protection working.",
             "Open a PR."],
            ["Branch protection won't enforce on private repo",
             "Free private repos don't enforce.",
             "Make repo public, OR upgrade to Pro."],
        ]),
        ("5.5 Nginx", [
            ["nginx: [emerg] unexpected end of file",
             "Syntax error.",
             "<i>sudo nginx -t</i> tells you the line."],
            ["403 Forbidden on / when proxying",
             "Default block intercepting.",
             "Remove <i>/etc/nginx/sites-enabled/default</i>."],
            ["SSE arrives in one burst at end",
             "<i>proxy_buffering on</i> default.",
             "Set <i>proxy_buffering off</i>."],
            ["Long request times out at 60s",
             "Default <i>proxy_read_timeout 60s</i>.",
             "Bump to <i>3600s</i>."],
            ["404 with right Host header",
             "<i>server_name</i> doesn't match.",
             "Add hostname or <i>_ + default_server</i>."],
        ]),
        ("5.6 Cloudflare", [
            ["521 Web server is down",
             "Origin unreachable.",
             "EC2 stopped? Restart."],
            ["522 Connection timed out",
             "Cloudflare can't connect to origin.",
             "SG missing 443. Add inbound rule."],
            ["523 Origin is unreachable",
             "DNS/route problem.",
             "Confirm A record IP."],
            ["525 SSL handshake failed",
             "TLS issue Cloudflare-origin.",
             "Cert hostname mismatch. Re-check 4.5."],
            ["526 Invalid SSL certificate",
             "Full strict + invalid cert.",
             "Regenerate Origin Certificate."],
            ["Browser shows self-signed warning",
             "Cloudflare set to Full, not Full strict.",
             "Switch to Full (strict)."],
            ["nslookup still shows old NS",
             "Propagation pending.",
             "Wait. Use <i>nslookup -type=NS DOMAIN 1.1.1.1</i>."],
        ]),
        ("5.7 GitHub Actions", [
            ["dial tcp ***:22: i/o timeout",
             "SG blocks runner IP.",
             "Open SSH 22 to 0.0.0.0/0 (after confirming key-only auth)."],
            ["Permission denied (publickey)",
             "EC2_SSH_KEY content wrong.",
             "Re-paste with <i>Get-Content key.pem -Raw | Set-Clipboard</i>."],
            ["Job hangs at 'Setting up Python'",
             "Cache lookup slow.",
             "Wait or remove <i>cache:</i> temporarily."],
            ["pytest fails in CI but passes locally",
             "Different Python or missing dep.",
             "Pin Python version; check requirements-dev."],
            ["Deploy ok but no new code on EC2",
             "Local uncommitted changes block git pull.",
             "<i>git status; git stash</i>, redeploy."],
            ["Cypress install hangs",
             "Network slow.",
             "Allow 5+ min."],
        ]),
        ("5.8 OS / disk / memory", [
            ["No space left on device",
             "Disk full.",
             "<i>docker image prune -a -f</i>."],
            ["fork: Resource temporarily unavailable",
             "OOM or process limit.",
             "Add swap; restart heavy services."],
            ["Service died no obvious error",
             "OOM-killed.",
             "<i>sudo journalctl -k | grep -i killed</i>."],
            ["Time wrong on EC2",
             "NTP not configured.",
             "<i>sudo timedatectl set-ntp true</i>."],
            ["Files end up owned by root",
             "Used sudo unnecessarily.",
             "<i>sudo chown -R ubuntu:ubuntu PATH</i>."],
        ]),
    ]
    for title, rows in sections:
        s.append(H2(title))
        wrapped = [["Symptom", "Cause", "Fix"]] + rows
        s.append(Tbl(wrapped, col_widths=[1.7*inch, 2.0*inch, 2.8*inch]))
        s.append(Sp(6))
    s.append(PB())


def build_runbook(s):
    s.append(H1("6. Operational Runbook"))
    s.append(H2("6.1 Daily smell-test"))
    s.append(Code(
        "curl --fail https://www.dhrubas.com.np/health\n"
        "ssh qa-agent\n"
        "docker compose ps\n"
        "df -h /\n"
        "free -h"))
    s.append(H2("6.2 Logs"))
    s.append(Tbl([
        ["Layer", "Location"],
        ["App stdout (Uvicorn, agents)", "<i>docker compose logs -f --tail=200</i>"],
        ["Cypress subprocess", "Same - captured by Python"],
        ["Nginx access", "<i>/var/log/nginx/access.log</i>"],
        ["Nginx error", "<i>/var/log/nginx/error.log</i>"],
        ["systemd unit", "<i>sudo journalctl -u nginx -n 100</i>"],
        ["Kernel (OOM)", "<i>sudo journalctl -k -p err</i>"],
        ["GitHub Actions", "github.com/USER/REPO/actions"],
    ], col_widths=[2.6*inch, 4.0*inch]))
    s.append(H2("6.3 Roll back a bad deploy"))
    s.append(Code(
        "ssh qa-agent\n"
        "cd /home/ubuntu/apps/qa_web_agent\n"
        "git log --oneline -n 10\n"
        "git reset --hard &lt;good-sha&gt;\n"
        "docker compose up -d --build\n"
        "curl --fail http://localhost:8000/health"))
    s.append(H2("6.4 Disk hygiene (weekly)"))
    s.append(Code(
        "df -h\n"
        "docker system df\n"
        "docker image prune -f\n"
        "sudo journalctl --vacuum-time=14d"))
    s.append(H2("6.5 Monitoring you should add later"))
    s.append(Tbl([
        ["Tool", "What it gives you"],
        ["Cloudflare Email Alerts", "Origin 5xx for &gt; N min"],
        ["CloudWatch alarms", "CPU &gt; 80%, disk &gt; 80%"],
        ["UptimeRobot / BetterUptime", "External health check"],
        ["GitHub Actions email", "On failed deploy (default)"],
        ["LangSmith", "Per-agent latency + tokens"],
    ], col_widths=[2.0*inch, 4.5*inch]))
    s.append(H2("6.6 Cost"))
    s.append(Tbl([
        ["Item", "USD/mo", "Notes"],
        ["t3.small 24/7", "$15.18", "Reserved instance halves it."],
        ["20 GB EBS gp3", "$1.60", "Per-GB-month."],
        ["Public IPv4 (EIP)", "$3.60", "Since Feb 2024."],
        ["Data transfer out", "$0-1", "First 100 GB free."],
        ["Cloudflare", "$0", "Free tier."],
        ["GitHub", "$0", "Public repo."],
        ["OpenAI", "$1-50", "Usage-dependent."],
        ["LangSmith", "$0", "5,000 traces/mo free."],
        ["<b>Typical total</b>", "<b>$22-70</b>", "Most variability is OpenAI."],
    ], col_widths=[1.8*inch, 1.5*inch, 3.2*inch]))
    s.append(H2("6.7 When to revisit the architecture"))
    s.append(P("Trigger a rewrite when: second EC2 needed (-&gt; load balancer); "
               "managed DB added; multi-engineer deploys; regulated data; "
               "cost &gt; $100/mo."))
    s.append(PB())


def build_glossary(s):
    s.append(H1("7. Glossary"))
    items = [
        ("AMI", "Amazon Machine Image - disk-image template an EC2 boots from."),
        ("ASGI", "Async Server Gateway Interface - Uvicorn-FastAPI protocol."),
        ("Branch protection", "GitHub rules on a branch (PRs required, status checks). Free on public; Pro+ on private."),
        ("BuildKit", "Modern Docker build engine. Fall back: DOCKER_BUILDKIT=0."),
        ("CD", "Continuous Deployment - auto-deploy of every passing change."),
        ("CI", "Continuous Integration - auto test on every change."),
        ("CIDR", "x.x.x.x/n IP ranges. 0.0.0.0/0 = whole internet; /32 = single IP."),
        ("Cloudflare proxy (orange cloud)", "Proxied = traffic goes through Cloudflare's edge, hiding your origin IP."),
        ("docker-compose", "YAML config to run multi-container apps."),
        ("EBS", "Elastic Block Store - AWS persistent block storage."),
        ("EC2", "Elastic Compute Cloud - basic VM service."),
        ("EIP", "Elastic IP - static IPv4 attachable to EC2."),
        ("FastAPI", "Modern Python web framework, async, SSE-friendly."),
        ("FHS", "Filesystem Hierarchy Standard - /etc /var /opt conventions."),
        ("GPG", "GNU Privacy Guard - signing/encryption. Used to verify Docker apt packages."),
        ("Heredoc", "command &lt;&lt;'EOF' ... EOF - sends content as stdin. Single-quoted EOF prevents shell expansion."),
        ("IAM", "Identity and Access Management - AWS users/roles/policies."),
        ("LangGraph", "Stateful multi-actor agent framework as a graph."),
        ("Layer caching (Docker)", "Each Dockerfile instruction is a hashed layer. COPY requirements.txt before COPY . . to protect pip install cache."),
        ("MFA", "Multi-Factor Auth - TOTP authenticator codes."),
        ("Nginx", "Web server / reverse proxy. On host, not in Docker."),
        ("Origin Certificate", "Cloudflare cert valid only Cloudflare-to-origin. 15 yr free."),
        ("Playwright", "Browser automation - drives Chromium for crawling."),
        ("Reverse proxy", "Server that forwards client requests to upstream."),
        ("Security Group", "AWS stateful firewall for EC2."),
        ("SSE", "Server-Sent Events - HTTP one-way streaming."),
        ("systemd", "Linux service manager."),
        ("TLS", "Transport Layer Security - HTTPS encryption."),
        ("Uvicorn", "ASGI server running FastAPI."),
        ("WSL2", "Windows Subsystem for Linux - Docker Desktop uses it."),
    ]
    s.append(Tbl(
        [["Term", "Definition"]] + [[k, v] for k, v in items],
        col_widths=[1.5*inch, 5.0*inch]
    ))
    s.append(Sp(20))
    s.append(Caption("End of document - qa-web-agent deployment guide"))


# ============================================================
# BUILD
# ============================================================
def main():
    doc = SimpleDocTemplate(
        OUT,
        pagesize=letter,
        leftMargin=0.75*inch,
        rightMargin=0.75*inch,
        topMargin=0.85*inch,
        bottomMargin=0.85*inch,
        title="QA-Web-Agent Deployment Guide",
        author="Dhrubas Sharma",
    )
    story = []
    build_title_page(story)
    build_toc(story)
    build_overview(story)
    build_phase_overview_page(story)
    build_phase_0(story)
    build_phase_1(story)
    build_phase_2(story)
    build_phase_3(story)
    build_phase_4(story)
    build_phase_5(story)
    build_linux_commands(story)
    build_cicd_doc(story)
    build_errors(story)
    build_runbook(story)
    build_glossary(story)
    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    print(f"Wrote: {OUT}")

if __name__ == "__main__":
    main()
